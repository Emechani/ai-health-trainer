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
            move(one('.record-reminder'), main, one('.mobile-coach-link'));
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
            fold(days, '요일별 전체 식단·운동 계획');
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
        reveal();
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
