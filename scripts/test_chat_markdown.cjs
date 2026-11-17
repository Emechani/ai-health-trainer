// 브라우저·외부 API 없이 허용된 DOM 요소와 텍스트 처리만 검증합니다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

class Element {
    constructor(tag, text = '') {
        this.tag = tag;
        this.children = [];
        this.value = text;
        this.attributes = {};
        this.classList = {add: () => {}};
    }
    appendChild(node) {
        if (node.tag === '#fragment') this.children.push(...node.children);
        else this.children.push(node);
        return node;
    }
    replaceChildren(...nodes) { this.children = []; this.value = ''; nodes.forEach(node => this.appendChild(node)); }
    set textContent(value) { this.value = String(value); this.children = []; }
    get textContent() { return this.value + this.children.map(node => node.textContent).join(''); }
    get lastElementChild() { return this.children.filter(node => !node.tag.startsWith('#')).at(-1); }
    set innerHTML(_) { throw new Error('Untrusted HTML insertion is forbidden'); }
    setAttribute(name, value) {
        assert.ok(['start', 'scope'].includes(name));
        this.attributes[name] = value;
    }
}

function renderer(initial = []) {
    const tags = new Set(['div', 'p', 'br', 'code', 'strong', 'em', 'h3', 'h4', 'h5', 'h6',
        'hr', 'pre', 'table', 'thead', 'tr', 'th', 'tbody', 'td', 'ol', 'ul', 'li', 'blockquote']);
    const document = {
        createElement(tag) { assert.ok(tags.has(tag)); return new Element(tag); },
        createTextNode(text) { return new Element('#text', text); },
        createDocumentFragment() { return new Element('#fragment'); },
        querySelectorAll(selector) { assert.equal(selector, '[data-ai-markdown]'); return initial; },
    };
    const context = {window: {}, document};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../records/static/records/chat_markdown.js'), 'utf8'), context);
    return text => {
        const container = new Element('div');
        context.window.renderChatMarkdown(container, text);
        return container;
    };
}

function find(node, tag) {
    return [node, ...node.children.flatMap(child => find(child, '*'))].filter(item => tag === '*' || item.tag === tag);
}

test('bold, emphasis, triple emphasis and inline code become readable elements', () => {
    const node = renderer()('**운동**과 *휴식*, ***균형***, `기록`');
    assert.equal(find(node, 'strong').length, 2);
    assert.equal(find(node, 'em').length, 2);
    assert.equal(find(node, 'code')[0].textContent, '기록');
    assert.equal(node.textContent, '운동과 휴식, 균형, 기록');
});

test('headings, nested lists, quotes and separators stay inside the message', () => {
    const node = renderer()('# 오늘 계획\n\n- 걷기\n  - 천천히\n- 휴식\n\n3. 식사\n4. 기록\n\n> 무리하지 마세요\n\n---');
    assert.equal(find(node, 'h3')[0].textContent, '오늘 계획');
    assert.equal(find(node, 'ul').length, 2);
    assert.equal(find(node, 'ol')[0].attributes.start, '3');
    assert.equal(find(node, 'blockquote').length, 1);
    assert.equal(find(node, 'hr').length, 1);
});

test('tables are rendered as cells with literal text', () => {
    const node = renderer()('| 식사 | 음식 |\n| --- | --- |\n| 아침 | **계란** |');
    assert.equal(find(node, 'table').length, 1);
    assert.equal(find(node, 'th').length, 2);
    assert.equal(find(node, 'td')[1].textContent, '계란');
});

test('HTML, event handlers, script URLs and SVG never create executable elements', () => {
    const payload = '<img src=x onerror=alert(1)>\n<script>alert(1)</script>\n<svg onload=alert(1)>\n[열기](javascript:alert(1))';
    const node = renderer()(payload);
    assert.equal(find(node, 'img').length, 0);
    assert.equal(find(node, 'script').length, 0);
    assert.equal(find(node, 'svg').length, 0);
    assert.equal(find(node, 'a').length, 0);
    assert.ok(node.textContent.includes('<img src=x onerror=alert(1)>'));
});

test('fenced HTML stays code and saved answers use the same formatter', () => {
    const stored = new Element('div', '**저장된 답변**');
    const render = renderer([stored]);
    assert.equal(find(stored, 'strong')[0].textContent, '저장된 답변');
    const node = render('```html\n<script>alert(1)</script>\n```');
    assert.equal(find(node, 'pre').length, 1);
    assert.equal(find(node, 'script').length, 0);
    assert.equal(find(node, 'code')[0].textContent, '<script>alert(1)</script>');
});
