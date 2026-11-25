(() => {
    const key = 'health-overview-theme';
    const preference = matchMedia('(prefers-color-scheme: dark)');
    let selected = 'system';
    try { const saved = localStorage.getItem(key); if (['dark', 'light', 'system'].includes(saved)) selected = saved; } catch (_) {}
    function apply() {
        const theme = selected === 'system' ? (preference.matches ? 'dark' : 'light') : selected;
        document.documentElement.dataset.theme = theme;
        document.querySelectorAll('[data-theme-select]').forEach(select => { select.value = selected; });
    }
    apply();
    preference.addEventListener('change', () => { if (selected === 'system') apply(); });
    document.addEventListener('DOMContentLoaded', () => {
        apply();
        document.querySelectorAll('[data-theme-select]').forEach(select => select.addEventListener('change', () => {
            if (!['light', 'dark', 'system'].includes(select.value)) return;
            selected = select.value;
            try { localStorage.setItem(key, selected); } catch (_) {}
            apply();
        }));
        // 고정된 선택 목록의 색상만 미리 보기에 사용합니다.
        const colors = {white:'#ffffff',sky:'#eaf0fb',mint:'#d5f7ed',green:'#cde9c9',lavender:'#e8def9',pink:'#fbdce7',peach:'#ffe3c9',navy:'#1d2b3e'};
        const select = document.querySelector('select[name="profile_color"]');
        if (select) {
            const preview = document.createElement('span');
            preview.className = 'profile-color-preview';
            preview.setAttribute('aria-hidden', 'true');
            select.after(preview);
            const update = () => { preview.style.backgroundColor = colors[select.value] || colors.white; };
            select.addEventListener('change', update);
            update();
        }
    });
})();
