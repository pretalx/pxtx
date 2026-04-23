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

// Inline-editable list cells: once an <select> is in the DOM, a change event
// POSTs the new value (htmx handles that). If the user opens the select and
// clicks away without picking anything different, no `change` fires and the
// cell would stay as a bare <select>. Revert to the display badge on blur.
document.addEventListener("focusout", (event) => {
    const select = event.target;
    if (!select || !select.matches || !select.matches(".edit-cell select")) return;
    const td = select.closest(".edit-cell");
    const url = select.dataset.revertUrl;
    if (!td || !url || !window.htmx) return;
    // Defer so the `change` POST (if any) runs first. If the cell is still
    // in edit mode after that, the user bailed — re-fetch the display.
    setTimeout(() => {
        if (td.isConnected && td.contains(select)) {
            window.htmx.ajax("GET", url, { target: td, swap: "outerHTML" });
        }
    }, 150);
});
