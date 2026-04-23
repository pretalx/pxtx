// Decorate <select class="enhanced"> elements with Choices.js.
// Choices keeps the native <select> in the DOM, so form submission and
// htmx's `change` trigger on the filter form keep working unchanged.

function initChoices(root) {
    if (typeof Choices === "undefined") return;
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("select.enhanced:not([data-choices-init])").forEach((select) => {
        select.setAttribute("data-choices-init", "1");
        new Choices(select, {
            removeItemButton: select.multiple,
            searchResultLimit: -1,
            shouldSort: false,
            resetScrollPosition: false,
            allowHTML: false,
            itemSelectText: "",
            placeholder: !!select.dataset.placeholder,
            placeholderValue: select.dataset.placeholder || null,
        });
    });
}

document.addEventListener("DOMContentLoaded", () => initChoices(document));
document.addEventListener("htmx:afterSwap", (event) => initChoices(event.target));
