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

// Markdown preview toggle. On first click htmx fetches the rendered preview
// and the `htmx:afterSwap` handler below reveals the pane. Further clicks
// toggle visibility without refetching, and the button label tracks state.
document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-preview-toggle]");
    if (!trigger) return;
    const target = document.querySelector(trigger.dataset.previewTarget);
    if (!target) return;
    if (!target.hasAttribute("hidden")) {
        // Preview is visible — hide it and stop htmx from refetching.
        event.preventDefault();
        event.stopPropagation();
        target.setAttribute("hidden", "");
        trigger.textContent = "Preview";
    }
    // Otherwise let htmx run; afterSwap flips the hidden flag.
});

document.addEventListener("htmx:afterSwap", (event) => {
    const target = event.target;
    if (!target || target.id !== "description-preview") return;
    target.removeAttribute("hidden");
    const trigger = document.querySelector('[data-preview-toggle][data-preview-target="#' + target.id + '"]');
    if (trigger) trigger.textContent = "Hide preview";
});
