// Drag-and-drop reordering for the issue list, wired when the table is
// sorted by priority (the only sort that respects ``order_in_priority``).
// The server re-renders the table on success and the fresh HTML is swapped
// in; the priority sort snaps rows back into their buckets, so cross-bucket
// drops just "bounce" visually without needing client-side rejection.
(function () {
    function reinit(container) {
        if (!window.Sortable) return;
        const table = container.querySelector("table.issue-table.reorderable");
        if (!table || table.dataset.reorderReady === "1") return;
        table.dataset.reorderReady = "1";

        const urlTemplate = container.dataset.reorderUrlTemplate;
        const csrfToken = container.dataset.csrfToken || "";
        const tbody = table.querySelector("tbody");

        window.Sortable.create(tbody, {
            animation: 120,
            handle: ".drag-col",
            ghostClass: "sortable-ghost",
            chosenClass: "sortable-chosen",
            onEnd(evt) {
                if (evt.oldIndex === evt.newIndex) return;
                const item = evt.item;
                const number = item.dataset.issueNumber;
                const priority = item.dataset.priority;
                // Index is relative to rows of the same priority bucket, so
                // the server can insert into the bucket at the right spot.
                const sameBucket = Array.prototype.filter.call(
                    tbody.querySelectorAll("tr"),
                    (r) => r.dataset.priority === priority,
                );
                const index = sameBucket.indexOf(item);
                const url = urlTemplate.replace(/\/0\/reorder\/$/, `/${number}/reorder/`);
                const form = new FormData();
                form.set("index", String(index));
                fetch(url, {
                    method: "POST",
                    headers: { "X-CSRFToken": csrfToken, "HX-Request": "true" },
                    body: form,
                    credentials: "same-origin",
                })
                    .then((response) => {
                        if (!response.ok) {
                            window.location.reload();
                            return null;
                        }
                        return response.text();
                    })
                    .then((html) => {
                        if (html === null) return;
                        const replacement = document.createElement("div");
                        replacement.innerHTML = html.trim();
                        const fresh = replacement.querySelector("#issue-table");
                        if (!fresh) return;
                        container.replaceWith(fresh);
                        reinit(fresh);
                    })
                    .catch(() => {
                        window.location.reload();
                    });
            },
        });
    }

    function boot() {
        const container = document.getElementById("issue-table");
        if (container) reinit(container);
    }

    document.addEventListener("DOMContentLoaded", boot);
    // The filter form swaps the table via htmx; re-arm Sortable after swaps.
    document.addEventListener("htmx:afterSwap", (evt) => {
        if (evt.target && evt.target.id === "issue-table") {
            reinit(evt.target);
        }
    });
})();
