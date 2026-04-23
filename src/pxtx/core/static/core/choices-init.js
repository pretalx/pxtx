// Decorate <select class="enhanced"> elements with Choices.js. The native
// <select> stays in the DOM, so form submission and htmx's `change` trigger
// on the filter form keep working unchanged.
//
// Selects that carry `data-badge-type` (the inline status/priority/effort
// cells in the issue table) get extra treatment: we copy the matching badge
// class onto each option's `data-label-class`, which Choices.js reads to
// wrap the rendered label in a `<span class="badge ...">` — so each choice
// in the dropdown and the currently-selected pill look identical to the
// read-only badge shown in the table cell.

function badgeClassFor(field, value) {
    if (!value) return null;
    if (field === "status") return "badge status-" + value;
    if (field === "priority") return "prio prio-" + value;
    if (field === "effort") return "badge effort-" + value;
    return null;
}

function decorateOptionsWithBadges(select) {
    const field = select.dataset.badgeType;
    if (!field) return;
    Array.from(select.options).forEach((opt) => {
        const cls = badgeClassFor(field, opt.value);
        if (cls) opt.dataset.labelClass = cls;
    });
}

function initChoices(root) {
    if (typeof Choices === "undefined") return;
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("select.enhanced:not([data-choices-init])").forEach((select) => {
        select.setAttribute("data-choices-init", "1");
        decorateOptionsWithBadges(select);
        // Choices.js copies `option.innerHTML` as the label. For labels with
        // HTML entities (e.g. "<1h", ">1d"), innerHTML returns the entity-
        // escaped form (`&gt;1d`), which Choices then re-escapes under
        // allowHTML:false, so the dropdown ends up showing "&gt;1d". Capture
        // the decoded textContent up front so we can re-seed labels below.
        const seeded = Array.from(select.options).map((opt) => ({
            value: opt.value,
            label: opt.textContent,
            selected: opt.selected,
            disabled: opt.disabled,
            labelClass: opt.dataset.labelClass || undefined,
        }));
        const inlineEdit = !!select.dataset.inlineEdit;
        const options = {
            removeItemButton: select.multiple,
            searchResultLimit: -1,
            shouldSort: false,
            resetScrollPosition: false,
            allowHTML: false,
            itemSelectText: "",
            placeholder: !!select.dataset.placeholder,
            placeholderValue: select.dataset.placeholder || null,
        };
        if (inlineEdit) options.searchEnabled = false;
        const instance = new Choices(select, options);
        instance.setChoices(seeded, "value", "label", true);
        select._choicesInstance = instance;
        if (inlineEdit) {
            // autofocus on the now-hidden native select does nothing; pop the
            // dropdown open after Choices finishes wiring up its listeners.
            requestAnimationFrame(() => instance.showDropdown());
        }
    });
}

function destroyChoicesIn(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("select[data-choices-init]").forEach((select) => {
        const instance = select._choicesInstance;
        if (!instance) return;
        try { instance.destroy(); } catch (_) { /* already torn down */ }
        delete select._choicesInstance;
    });
}

document.addEventListener("DOMContentLoaded", () => initChoices(document));
document.addEventListener("htmx:afterSwap", (event) => initChoices(event.target));
document.addEventListener("htmx:beforeCleanupElement", (event) => destroyChoicesIn(event.target));
