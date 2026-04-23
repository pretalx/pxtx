// Global keyboard shortcuts. We deliberately keep this tiny: a single key
// dispatcher, a `g` prefix for navigation (vim-style), and a help dialog.
// The listener bails out immediately when focus is inside a form field so
// shortcuts never clobber typing.

const NAV_TARGETS = {
    d: "/",
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
        window.location.href = "/issues/new/";
    }
});

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

// Issue edit modal wiring for the list and kanban views. Clicking an issue
// title triggers an htmx GET into #issue-modal; once the form fragment is in
// the DOM we pop the dialog open. On save, the server answers 204 +
// `HX-Trigger: pxtx:issue-saved`; we close the dialog and refresh whichever
// container is on screen so sort/filter state stays honest without a full
// page reload. Validation errors keep the dialog open because the server
// re-renders the fragment back into #issue-modal (no trigger fires).
function getIssueModal() {
    return document.getElementById("issue-modal");
}

function closeIssueModal() {
    const modal = getIssueModal();
    if (!modal) return;
    if (modal.open) modal.close();
    modal.innerHTML = "";
}

document.addEventListener("htmx:afterSwap", (event) => {
    const target = event.target;
    if (!target || target.id !== "issue-modal") return;
    if (!target.innerHTML.trim()) return;
    if (typeof target.showModal !== "function") return;
    if (!target.open) target.showModal();
});

document.addEventListener("click", (event) => {
    const closer = event.target.closest("[data-modal-close]");
    if (!closer) return;
    const modal = closer.closest("dialog.issue-modal");
    if (!modal) return;
    event.preventDefault();
    closeIssueModal();
});

document.addEventListener("click", (event) => {
    const modal = getIssueModal();
    if (!modal || !modal.open) return;
    // <dialog> treats clicks on the backdrop as events on itself.
    if (event.target === modal) closeIssueModal();
});

document.addEventListener("close", (event) => {
    // Clear stale form HTML so the next open fetches fresh contents.
    if (event.target && event.target.id === "issue-modal") {
        event.target.innerHTML = "";
    }
}, true);

document.addEventListener("pxtx:issue-saved", () => {
    closeIssueModal();
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
