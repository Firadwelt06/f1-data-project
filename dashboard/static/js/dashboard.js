// Generic click-to-sort for any <table class="sortable"> whose <th> cells
// carry a data-sort="text|numeric" attribute. Re-used across the win %,
// dominance, and win-streaks pages rather than duplicated per template.
document.querySelectorAll('table.sortable thead th').forEach((th, index) => {
    if (!th.dataset.sort) return;

    th.style.cursor = 'pointer';
    let ascending = th.dataset.sortDefault !== 'desc';

    th.addEventListener('click', () => {
        const table = th.closest('table');
        const tbody = table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));
        const type = th.dataset.sort;

        rows.sort((a, b) => {
            let aVal = a.children[index].textContent.trim();
            let bVal = b.children[index].textContent.trim();

            if (type === 'numeric') {
                aVal = parseFloat(aVal.replace('%', '')) || 0;
                bVal = parseFloat(bVal.replace('%', '')) || 0;
                return ascending ? aVal - bVal : bVal - aVal;
            }
            return ascending ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
        });

        ascending = !ascending;
        rows.forEach((row) => tbody.appendChild(row));
    });
});

// Decade filter dropdown on the constructor dominance page. Harmless no-op
// on every other page since the element simply won't be found there.
const decadeFilter = document.getElementById('decade-filter');
if (decadeFilter) {
    decadeFilter.addEventListener('change', () => {
        const value = decadeFilter.value;
        document.querySelectorAll('#dominance-table tbody tr').forEach((row) => {
            row.style.display = (value === 'all' || row.dataset.decade === value) ? '' : 'none';
        });
    });
}
