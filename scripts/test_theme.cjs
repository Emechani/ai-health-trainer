const assert = require('node:assert/strict');
const {test} = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../main/static/main/theme.js'), 'utf8');
function boot(saved, dark = false, blocked = false) {
    const store = new Map(saved ? [['health-overview-theme', saved]] : []);
    const handlers = {};
    const control = {value:'system', addEventListener(name, fn) { handlers[name] = fn; }};
    const events = {};
    const preference = {matches:dark, addEventListener(name, fn) { this.changed = fn; }};
    const document = {documentElement:{dataset:{}}, querySelectorAll:() => [control], querySelector:() => null,
        addEventListener(name, fn) {events[name] = fn; }};
    const storage = {getItem(key) {if (blocked) throw Error('blocked'); return store.get(key);},
        setItem(key, value) {if (blocked) throw Error('blocked'); store.set(key, value);}};
    vm.runInNewContext(source, {document,localStorage:storage,matchMedia:()=>preference});
    events.DOMContentLoaded();
    return {document,control,store,choose(value) {control.value=value;handlers.change();},
        system(dark) {preference.matches=dark;preference.changed();}};
}
test('default follows device and updates when device changes', () => {
    const ui = boot(undefined, true);
    assert.equal(ui.document.documentElement.dataset.theme, 'dark');
    assert.equal(ui.control.value, 'system');
    ui.system(false);
    assert.equal(ui.document.documentElement.dataset.theme, 'light');
});
test('explicit choice persists and takes priority over device', () => {
    const ui = boot('dark', false);
    assert.equal(ui.control.value, 'dark');
    ui.choose('light');ui.system(true);
    assert.equal(ui.document.documentElement.dataset.theme, 'light');
    assert.equal(boot(ui.store.get('health-overview-theme'), true).control.value, 'light');
});
test('switching back to system restores device preference', () => {
    const ui = boot('light', true);ui.choose('system');
    assert.equal(ui.document.documentElement.dataset.theme, 'dark');
    assert.equal(ui.store.get('health-overview-theme'), 'system');
});
test('invalid saved setting and blocked storage remain usable', () => {
    assert.equal(boot('invalid', false).control.value, 'system');
    const ui = boot(undefined, false, true);ui.choose('dark');
    assert.equal(ui.document.documentElement.dataset.theme, 'dark');
});
