(function () {
  'use strict';

  var root = document.querySelector('[data-lab-root]');
  if (!root) return;

  var statePanels = root.querySelectorAll('[data-lab-state-panel]');
  var stateButtons = root.querySelectorAll('[data-lab-state]');
  var dialog = root.querySelector('[data-lab-dialog]');
  var confirmDialog = root.querySelector('[data-lab-confirm-dialog]');
  var drawer = root.querySelector('[data-lab-drawer]');
  var toast = root.querySelector('[data-lab-toast]');
  var search = root.querySelector('[data-lab-search]');
  var filter = root.querySelector('[data-lab-filter]');
  var sort = root.querySelector('[data-lab-sort]');
  var items = Array.prototype.slice.call(root.querySelectorAll('[data-lab-item]'));
  var list = root.querySelector('[data-lab-list]');
  var count = root.querySelector('[data-lab-count]');

  function setState(state) {
    statePanels.forEach(function (panel) { panel.hidden = panel.dataset.labStatePanel !== state; });
    stateButtons.forEach(function (button) { button.setAttribute('aria-pressed', String(button.dataset.labState === state)); });
  }

  function showToast(message) {
    toast.textContent = message || 'Preview action completed.';
    toast.hidden = false;
    window.setTimeout(function () { toast.hidden = true; }, 2200);
  }

  function closeMenus(except) {
    root.querySelectorAll('.lab-menu').forEach(function (menu) {
      if (menu !== except) {
        menu.hidden = true;
        menu.previousElementSibling.setAttribute('aria-expanded', 'false');
      }
    });
  }

  function updateList() {
    if (!search || !filter) return;
    var term = search.value.trim().toLowerCase();
    var visible = 0;
    items.forEach(function (item) {
      var match = (!term || item.dataset.name.indexOf(term) >= 0 || item.dataset.id.indexOf(term) >= 0) && (filter.value === 'all' || item.dataset.status === filter.value);
      item.hidden = !match;
      if (match) visible += 1;
    });
    if (count) count.textContent = String(visible);
    if (!visible) setState('empty');
  }

  if (search) search.addEventListener('input', updateList);
  if (filter) filter.addEventListener('change', updateList);
  if (sort) sort.addEventListener('change', function () {
    items.sort(function (left, right) {
      if (sort.value === 'attention') return Number(right.dataset.attention) - Number(left.dataset.attention);
      return left.dataset.name.localeCompare(right.dataset.name);
    }).forEach(function (item) { list.appendChild(item); });
  });

  root.addEventListener('click', function (event) {
    var state = event.target.closest('[data-lab-state]');
    var menuButton = event.target.closest('[data-lab-menu-button]');
    if (state) setState(state.dataset.labState);
    else if (event.target.closest('[data-lab-dialog-open]')) { dialog.showModal(); dialog.querySelector('[data-lab-dialog-input]').focus(); }
    else if (event.target.closest('[data-lab-confirm]')) confirmDialog.showModal();
    else if (event.target.closest('[data-lab-feedback]')) { event.preventDefault(); showToast(); }
    else if (event.target.closest('[data-lab-drawer-open]')) { drawer.hidden = false; drawer.querySelector('button').focus(); }
    else if (event.target.closest('[data-lab-drawer-close]')) { drawer.hidden = true; }
    else if (menuButton) {
      var menu = menuButton.nextElementSibling;
      var open = menu.hidden;
      closeMenus(menu);
      menu.hidden = !open;
      menuButton.setAttribute('aria-expanded', String(open));
      if (open) menu.querySelector('[role="menuitem"]').focus();
    } else if (!event.target.closest('.lab-menu')) closeMenus();
  });

  root.querySelectorAll('[data-lab-dialog-save], [data-lab-confirm-save]').forEach(function (button) {
    button.addEventListener('click', function (event) {
      event.preventDefault();
      button.closest('dialog').close();
      setState('success');
    });
  });

  root.querySelectorAll('[data-lab-form]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var invalid = form.querySelector(':invalid');
      var summary = form.querySelector('.lab-error-summary');
      if (invalid) {
        invalid.setAttribute('aria-invalid', 'true');
        summary.hidden = false;
        summary.focus();
      } else setState('success');
    });
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') { closeMenus(); if (drawer) drawer.hidden = true; }
  });
}());