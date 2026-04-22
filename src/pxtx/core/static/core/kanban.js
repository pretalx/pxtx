// Kanban drag-and-drop for the milestone detail view. Wires SortableJS
// onto each column; on drop, POSTs (issue, column, index) to the server
// and lets the server truth win by swapping the board HTML back in.
(function () {
    function init(board) {
        if (!window.Sortable || board.dataset.kanbanReady === "1") return;
        board.dataset.kanbanReady = "1";
        const moveUrl = board.dataset.moveUrl;
        const csrfToken = board.dataset.csrfToken || "";
        const cols = board.querySelectorAll(".kanban-cards");
        cols.forEach((col) => {
            window.Sortable.create(col, {
                group: "kanban",
                animation: 120,
                ghostClass: "sortable-ghost",
                chosenClass: "sortable-chosen",
                onEnd(evt) {
                    const item = evt.item;
                    const number = item.getAttribute("data-issue-number");
                    const column = evt.to.getAttribute("data-column");
                    const index = Array.prototype.indexOf.call(
                        evt.to.querySelectorAll(".kanban-card"),
                        item,
                    );
                    const form = new FormData();
                    form.set("issue", number);
                    form.set("column", column);
                    form.set("index", String(index));
                    fetch(moveUrl, {
                        method: "POST",
                        headers: { "X-CSRFToken": csrfToken },
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
                            const fresh = replacement.querySelector(".kanban");
                            if (!fresh) return;
                            board.replaceWith(fresh);
                            init(fresh);
                        })
                        .catch(() => {
                            window.location.reload();
                        });
                },
            });
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll(".kanban").forEach(init);
    });
})();
