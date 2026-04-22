// Keyboard shortcut: `/` focuses the search box on the issue list.
document.addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.target.matches("input, textarea, select")) return;
    const search = document.querySelector("input[name=search]");
    if (!search) return;
    event.preventDefault();
    search.focus();
    search.select();
});
