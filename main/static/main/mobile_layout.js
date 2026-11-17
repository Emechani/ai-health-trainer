/* 같은 DOM과 이벤트를 유지한 채 모바일에서만 보조 내용을 접습니다. */
(() => {
    const body = document.body;
    if (!body.classList.contains('stitch-app')) return;
    const media = matchMedia('(max-width: 760px)');
    const undo = [];
    const one = selector => document.querySelector(selector);
    const all = selector => [...document.querySelectorAll(selector)];
    function move(node, parent, before = null) {
        if (!node || !parent) return;
        const marker = document.createComment('mobile-origin');
        node.before(marker);
        parent.insertBefore(node, before);
        undo.push(() => { marker.replaceWith(node); });
    }
    function fold(nodes, title, open = false) {
        nodes = nodes.filter(Boolean);
        if (!nodes.length) return;
        const details = document.createElement('details');
        details.className = 'mobile-fold';
        details.open = open || nodes.some(node => node.querySelector('.errorlist, .has-error'));
        const summary = document.createElement('summary');
        summary.textContent = title;
        nodes[0].before(details);
        details.append(summary);
        undo.push(() => details.remove());
        nodes.forEach(node => move(node, details));
    }
    function reveal() {
        if (!media.matches || !location.hash) return;
        const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
        if (!target) return;
        let parent = target;
        while (parent) { if (parent.tagName === 'DETAILS') parent.open = true; parent = parent.parentElement; }
        target.scrollIntoView({block: 'start'});
    }
    function layout() {
        while (undo.length) undo.pop()();
        body.classList.toggle('mobile-chat-open', new URL(location.href).searchParams.get('chat') === '1');
        if (!media.matches) return;
        if (body.classList.contains('page-home')) {
            const main = one('.main-content');
            const steps = one('.summary-cards .stat-card');
            const sync = one('#steps-sync-form');
            if (steps && sync) {
                const slot = document.createElement('div');
                slot.className = 'mobile-steps-sync';
                steps.after(slot);
                undo.push(() => slot.remove());
                move(sync, slot);
                move(one('#steps-sync-progress'), slot);
            }
            const quick = one('.mobile-quick-actions');
            move(one('.summary-cards'), main, quick);
            move(one('.record-reminder'), main, one('.today-plan-card, .mobile-empty-plan') || one('.summary-cards'));
            fold(all('.summary-cards .stat-card').slice(1), '섭취·소모 열량 자세히 보기');
            fold([one('.nutrition-preview')], '영양 기록과 보완 안내');
            fold([one('.week-summary')?.closest('.activity-card')], '이번 주 활동 기록');
            fold([one('#google-fit-heading')?.closest('section')], 'Google 연결 상태·재인증');
            const cards = all('.right-panel > .dark-card');
            fold(cards.slice(0,1), '내 체중 목표 요약');
            fold(cards.slice(1), '기록 안내');
        }
        if (body.classList.contains('page-goals')) {
            const main = one('.main-content');
            const today = one('.goal-today');
            if (today) move(today, main, one('.header-wrapper')?.nextElementSibling);
            fold([one('#food-options')], '음식 선호·알레르기 설정', !!one('#weekly-goal-form'));
            fold([one('#nutrition')], '영양 기록과 보완 안내');
            fold(all('.main-content > .goal-grid'), '실천 현황');
            const days = all('.main-content > .goal-day');
            const intro = days[0]?.previousElementSibling;
            const introNodes = intro?.querySelector('h2')?.textContent.includes('요일별 실천 계획') ? [intro] : [];
            fold([...introNodes, ...days], '이번 주 전체 계획');
            const archive = one('.goal-select')?.closest('section');
            const generator = all('.main-content > section.card').find(section => section.querySelector('h2')?.textContent.includes('AI가 정해 주는'));
            if (archive && generator && !one('#weekly-goal-form')) fold([generator, archive], '이전 계획 보기');
            all('.main-content > section.card').forEach(section => {
                if (section === today) return;
                const heading = section.querySelector('h2');
                if (!heading || section.querySelector('#weekly-goal-form')) return;
                fold([section], heading.textContent.trim());
            });
        }
        if (body.classList.contains('page-profile')) {
            fold([one('#profile-heading')?.closest('section')], '프로필·체중 목표 수정');
            fold([one('#exercise-habits')], '운동 습관 설정');
            fold([one('#weight-history')], '체중 기록과 변화');
            fold([one('.security-card')], '계정 보안');
        }
        if (body.classList.contains('page-exercise')) {
            const start = one('#id_start_time')?.closest('p');
            const end = one('#id_end_time')?.closest('p');
            if (start && end) {
                const grid = document.createElement('div');
                grid.className = 'mobile-time-grid';
                start.before(grid);
                undo.push(() => grid.remove());
                move(start, grid);
                move(end, grid);
            }
        }
        reveal();
    }
    // 실제 입력한 시작·종료 시각으로만 운동 시간을 표시합니다.
    if (body.classList.contains('page-exercise')) {
        const start = one('#id_start_time');
        const end = one('#id_end_time');
        if (start && end) {
            const duration = document.createElement('div');
            duration.className = 'mobile-only mobile-duration';
            duration.setAttribute('role', 'status');
            end.closest('p').after(duration);
            const label = document.createElement('span');
            label.textContent = '예상 총 운동 시간';
            const value = document.createElement('strong');
            duration.append(label, value);
            const minutes = text => { const parts = text.split(':').map(Number); return parts.length >= 2 ? parts[0] * 60 + parts[1] : NaN; };
            const update = () => {
                const difference = minutes(end.value) - minutes(start.value);
                value.textContent = Number.isFinite(difference) && difference > 0 ? `${difference}분` : '시간을 선택해 주세요';
            };
            start.addEventListener('input', update);
            end.addEventListener('input', update);
            update();
        }
    }
    // 사진은 브라우저 안에서 미리 보기만 하며, 저장 전에는 서버로 전송하지 않습니다.
    if (body.classList.contains('page-meals')) {
        const input = one('input[type=file]');
        if (input) {
            const preview = document.createElement('div');
            preview.className = 'mobile-photo-preview';
            preview.hidden = true;
            const image = document.createElement('img');
            image.alt = '선택한 식사 사진 미리보기';
            const clear = document.createElement('button');
            clear.type = 'button'; clear.textContent = '✕'; clear.setAttribute('aria-label', '선택한 사진 제거');
            preview.append(image, clear);
            input.closest('p').after(preview);
            let url;
            const update = () => {
                if (url) URL.revokeObjectURL(url);
                const file = input.files[0];
                const valid = !!file && file.type.startsWith('image/');
                preview.hidden = !valid;
                if (valid) { url = URL.createObjectURL(file); image.src = url; }
                else { image.removeAttribute('src'); url = null; }
            };
            input.addEventListener('change', update);
            clear.addEventListener('click', () => { input.value = ''; update(); input.focus(); });
            window.addEventListener('pagehide', () => { if (url) URL.revokeObjectURL(url); });
        }
    }
    const dialog = one('#mobile-record-sheet');
    const trigger = one('#mobile-record-open');
    trigger?.addEventListener('click', () => dialog.showModal());
    one('#mobile-record-close')?.addEventListener('click', () => dialog.close());
    dialog?.addEventListener('click', event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientY < r.top || event.clientX < r.left || event.clientX > r.right) dialog.close(); } });
    dialog?.addEventListener('close', () => trigger?.focus());
    document.addEventListener('invalid', event => {
        let node = event.target.parentElement;
        while (node) { if (node.tagName === 'DETAILS') node.open = true; node = node.parentElement; }
    }, true);
    window.addEventListener('hashchange', reveal);
    media.addEventListener('change', () => { if (!media.matches) dialog?.close(); layout(); });
    layout();
})();
