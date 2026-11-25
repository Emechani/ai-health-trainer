(() => {
    const key = 'health-overview-theme';
    const preference = matchMedia('(prefers-color-scheme: dark)');
    let selected = null;
    try { const saved = localStorage.getItem(key); if (saved === 'dark' || saved === 'light') selected = saved; } catch (_) {}
    function apply(theme) {
        document.documentElement.dataset.theme = theme;
        document.querySelectorAll('[data-theme-toggle]').forEach(button => {
            button.textContent = theme === 'dark' ? '라이트 모드 켜기' : '다크 모드 켜기';
            button.setAttribute('aria-label', theme === 'dark' ? '라이트 모드 켜기' : '다크 모드 켜기');
            button.setAttribute('aria-pressed', String(theme === 'dark'));
        });
    }
    apply(selected || (preference.matches ? 'dark' : 'light'));
    preference.addEventListener('change', () => { if (!selected) apply(preference.matches ? 'dark' : 'light'); });
    document.addEventListener('DOMContentLoaded', () => {
        apply(document.documentElement.dataset.theme);
        document.querySelectorAll('[data-theme-toggle]').forEach(button => button.addEventListener('click', () => {
            selected = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
            try { localStorage.setItem(key, selected); } catch (_) {}
            apply(selected);
        }));
        // 고정된 선택 목록의 색상만 미리 보기에 사용합니다.
        const colors = {sky:'#eaf0fb',mint:'#d5f7ed',green:'#cde9c9',lavender:'#e8def9',pink:'#fbdce7',peach:'#ffe3c9',navy:'#1d2b3e'};
        const select = document.querySelector('select[name="profile_color"]');
        if (select) {
            const preview = document.createElement('span');
            preview.className = 'profile-color-preview';
            preview.setAttribute('aria-hidden', 'true');
            select.after(preview);
            const update = () => { preview.style.backgroundColor = colors[select.value] || colors.sky; };
            select.addEventListener('change', update);
            update();
        }
    });
})();
