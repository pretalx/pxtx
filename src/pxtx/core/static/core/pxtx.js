// Global keyboard shortcuts. We deliberately keep this tiny: a single key
// dispatcher, a `g` prefix for navigation (vim-style), and a help dialog.
// The listener bails out immediately when focus is inside a form field so
// shortcuts never clobber typing.

const NAV_TARGETS = {
    d: "/dashboard/",
    i: "/issues/",
    r: "/milestones/",
    a: "/activity/",
};

let gPrefixTimer = null;

function clearGPrefix() {
    gPrefixTimer = null;
    document.body.removeAttribute("data-g-prefix");
}

function armGPrefix() {
    document.body.setAttribute("data-g-prefix", "1");
    if (gPrefixTimer) clearTimeout(gPrefixTimer);
    gPrefixTimer = setTimeout(clearGPrefix, 1200);
}

function openHelp() {
    const dialog = document.getElementById("help-dialog");
    if (!dialog || typeof dialog.showModal !== "function") return;
    if (!dialog.open) dialog.showModal();
}

function isTypingTarget(el) {
    if (!el) return false;
    if (el.isContentEditable) return true;
    return el.matches("input, textarea, select, [contenteditable='true']");
}

document.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const typing = isTypingTarget(event.target);

    if (event.key === "Escape") {
        const dialog = document.getElementById("help-dialog");
        if (dialog && dialog.open) {
            event.preventDefault();
            dialog.close();
        }
        return;
    }

    if (typing) return;

    if (document.body.getAttribute("data-g-prefix")) {
        const target = NAV_TARGETS[event.key];
        clearGPrefix();
        if (target) {
            event.preventDefault();
            window.location.href = target;
        }
        return;
    }

    if (event.key === "g") {
        event.preventDefault();
        armGPrefix();
        return;
    }
    if (event.key === "?") {
        event.preventDefault();
        openHelp();
        return;
    }
    if (event.key === "/") {
        const search = document.querySelector("input[name=search]");
        if (!search) return;
        event.preventDefault();
        search.focus();
        search.select();
        return;
    }
    if (event.key === "c") {
        event.preventDefault();
        openCreateIssueModal();
    }
});

function openCreateIssueModal() {
    // Delegate to the nav "+ New" trigger so htmx picks up its hx-get and
    // target attributes. Falls back to the full-page form if the trigger
    // isn't on screen (e.g. unauthenticated).
    const trigger = document.querySelector(".new-issue[hx-get]");
    if (trigger) {
        trigger.click();
        return;
    }
    window.location.href = "/issues/new/";
}

document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-help-toggle]");
    if (!trigger) return;
    event.preventDefault();
    openHelp();
});

// Deploy-in-progress: after the /deploy/ POST swaps the form for the
// "Deploying…" indicator, poll /healthz/ and reload once the server answers
// 200 a few times in a row (so we don't reload mid-restart).
function initDeployPollers(root) {
    const scope = root && root.querySelectorAll ? root : document;
    const nodes = scope.querySelectorAll("[data-healthz-url]:not([data-healthz-init])");
    nodes.forEach((el) => {
        el.setAttribute("data-healthz-init", "1");
        const url = el.dataset.healthzUrl;
        let ok = 0;
        const poll = () => {
            fetch(url, { cache: "no-store" })
                .then((r) => {
                    if (r.ok) {
                        ok += 1;
                        if (ok >= 3) {
                            window.location.reload();
                            return;
                        }
                    } else {
                        ok = 0;
                    }
                })
                .catch(() => { ok = 0; })
                .finally(() => { setTimeout(poll, 2000); });
        };
        setTimeout(poll, 5000);
    });
}

document.addEventListener("htmx:afterSwap", () => initDeployPollers(document));
document.addEventListener("DOMContentLoaded", () => initDeployPollers(document));

// Issue edit/create modal wiring. The edit flow targets `#issue-modal`
// (which is a <dialog> on most pages but a sidebar <aside> on the issue
// list) and the create flow targets `#issue-create-modal` (always a
// <dialog>). Both reuse the same form fragment, so the modal wiring is
// shared. On save, the edit view answers 204 + `HX-Trigger: pxtx:issue-saved`
// and we refresh the container in place; the create view answers 204 +
// `HX-Redirect` which htmx handles natively. Validation errors re-render
// the fragment back into the same target, keeping the dialog open.
const ISSUE_MODAL_IDS = ["issue-modal", "issue-create-modal"];

function getIssueModal(id = "issue-modal") {
    return document.getElementById(id);
}

function closeModalElement(modal) {
    if (!modal) return;
    if (typeof modal.close === "function" && modal.open) modal.close();
    modal.innerHTML = "";
}

function isIssueModal(el) {
    return !!(el && el.id && ISSUE_MODAL_IDS.includes(el.id));
}

document.addEventListener("htmx:afterSwap", (event) => {
    const target = event.target;
    if (!isIssueModal(target)) return;
    if (!target.innerHTML.trim()) return;
    // Dialogs need to be popped open; sidebar asides are visible via CSS.
    if (typeof target.showModal !== "function") return;
    if (!target.open) target.showModal();
});

document.addEventListener("click", (event) => {
    const closer = event.target.closest("[data-modal-close]");
    if (!closer) return;
    const modal = closer.closest("#issue-modal, #issue-create-modal");
    if (!modal) return;
    event.preventDefault();
    closeModalElement(modal);
});

document.addEventListener("click", (event) => {
    // <dialog> treats clicks on the backdrop as events on itself. The sidebar
    // aside has no `open` property and does not receive these, so it is
    // unaffected — outside clicks never close the sidebar by design.
    if (!isIssueModal(event.target)) return;
    if (!event.target.open) return;
    closeModalElement(event.target);
});

document.addEventListener("close", (event) => {
    // Clear stale form HTML so the next open fetches fresh contents.
    if (isIssueModal(event.target)) {
        event.target.innerHTML = "";
    }
}, true);

document.addEventListener("pxtx:issue-saved", () => {
    closeModalElement(getIssueModal());
    if (!window.htmx) return;
    const table = document.getElementById("issue-table");
    if (table) {
        window.htmx.ajax("GET", window.location.href, {
            target: "#issue-table",
            swap: "outerHTML",
            select: "#issue-table",
        });
        return;
    }
    const board = document.querySelector(".kanban");
    if (board) {
        window.htmx.ajax("GET", window.location.href, {
            target: ".kanban",
            swap: "outerHTML",
            select: ".kanban",
        });
    }
});

// Click-to-edit text fields inside the issue modal: the read-only view is
// swapped for the underlying input on click. We bail when the click lands on
// a link/control inside the view (e.g. a PX-### reference in the rendered
// description), so navigating cross-references still works without tipping
// the field into edit mode.
document.addEventListener("click", (event) => {
    const target = event.target;
    if (!target || !target.closest) return;
    if (target.closest("a, button, input, textarea, select, label")) return;
    const view = target.closest("[data-inline-edit-view]");
    if (!view) return;
    const wrap = view.closest("[data-inline-edit]");
    if (!wrap || wrap.classList.contains("editing")) return;
    event.preventDefault();
    wrap.classList.add("editing");
    const input = wrap.querySelector(".inline-edit-field input, .inline-edit-field textarea");
    if (!input) return;
    input.focus();
    if (typeof input.setSelectionRange === "function") {
        const end = input.value.length;
        input.setSelectionRange(end, end);
    }
});

// Row-level click opens the issue sidebar. Nested interactive elements
// (links, editable cells, drag handle, form controls) keep their own
// behavior — we only fire when the click landed on "dead" row space.
document.addEventListener("click", (event) => {
    const target = event.target;
    if (!target || !target.closest) return;
    if (target.closest("a, button, input, select, textarea, label, .drag-col, .edit-cell")) return;
    const row = target.closest("tr[data-issue-href]");
    if (!row || !window.htmx) return;
    event.preventDefault();
    window.htmx.ajax("GET", row.dataset.issueHref, {
        target: "#issue-modal",
        swap: "innerHTML",
    });
});

// Inline-editable list cells: once a <select> is in the DOM, a change event
// POSTs the new value (htmx handles that). If the user opens the widget and
// clicks away without picking anything different, no `change` fires and the
// cell would stay in edit mode. Revert to the display badge on blur.
//
// Choices.js hides the native <select> and focus lives on its own wrapper,
// so we key off the `.edit-cell.editing` container instead of the select
// itself. We also bail if focus is still inside the cell — Choices moves
// focus between its internal elements as the user interacts with the
// dropdown, and each hop fires focusout.
document.addEventListener("focusout", (event) => {
    const cell = event.target.closest && event.target.closest(".edit-cell.editing");
    if (!cell || !window.htmx) return;
    const select = cell.querySelector("select");
    const url = select && select.dataset.revertUrl;
    if (!url) return;
    setTimeout(() => {
        if (!cell.isConnected) return;
        if (!cell.classList.contains("editing")) return;
        if (cell.contains(document.activeElement)) return;
        window.htmx.ajax("GET", url, { target: cell, swap: "outerHTML" });
    }, 150);
});
