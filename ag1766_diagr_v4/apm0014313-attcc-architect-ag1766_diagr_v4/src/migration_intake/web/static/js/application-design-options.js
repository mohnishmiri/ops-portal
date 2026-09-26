(function () {
  'use strict';

  var root = document.querySelector('[data-application-preview]');
  if (!root) return;

  var cards = Array.prototype.slice.call(root.querySelectorAll('.preview-card'));
  var cardRegion = root.querySelector('[data-preview-cards]');
  var search = root.querySelector('[data-preview-search]');
  var filter = root.querySelector('[data-preview-filter]');
  var sort = root.querySelector('[data-preview-sort]');
  var count = root.querySelector('[data-preview-count]');
  var loading = root.querySelector('[data-preview-loading]');
  var empty = root.querySelector('[data-preview-empty]');
  var error = root.querySelector('[data-preview-error]');
  var toast = root.querySelector('[data-preview-toast]');
  var dialog = root.querySelector('[data-preview-dialog]');

  function applyFilters() {
    var term = search.value.trim().toLowerCase();
    var status = filter.value;
    var visible = 0;
    cards.forEach(function (card) {
      var matchesText = !term || card.dataset.name.indexOf(term) >= 0 || card.dataset.id.indexOf(term) >= 0;
      var matchesStatus = status === 'all' || card.dataset.status === status;
      card.hidden = !(matchesText && matchesStatus);
      card.classList.toggle('is-filtered', card.hidden);
      if (!card.hidden) visible += 1;
    });
    count.textContent = String(visible);
    empty.hidden = visible !== 0;
    cardRegion.hidden = visible === 0;
  }

  function applySort() {
    cards.sort(function (left, right) {
      if (sort.value === 'attention') return Number(right.dataset.attention) - Number(left.dataset.attention);
      if (sort.value === 'activity') return Number(right.dataset.activity) - Number(left.dataset.activity);
      return left.dataset.name.localeCompare(right.dataset.name);
    }).forEach(function (card) { cardRegion.appendChild(card); });
  }

  function closeMenus(except) {
    root.querySelectorAll('[data-preview-menu]').forEach(function (menu) {
      if (menu !== except) {
        menu.hidden = true;
        menu.previousElementSibling.setAttribute('aria-expanded', 'false');
      }
    });
  }

  function setState(state) {
    root.querySelectorAll('[data-preview-state]').forEach(function (button) {
      var active = button.dataset.previewState === state;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    loading.hidden = state !== 'loading';
    error.hidden = state !== 'error';
    cardRegion.hidden = state !== 'populated';
    empty.hidden = state !== 'empty';
    if (state === 'populated') applyFilters();
  }

  function showFeedback(message) {
    toast.textContent = message;
    toast.hidden = false;
    window.setTimeout(function () { toast.hidden = true; }, 2400);
  }

  search.addEventListener('input', applyFilters);
  filter.addEventListener('change', applyFilters);
  sort.addEventListener('change', applySort);
  document.addEventListener('click', function (event) {
    var menuButton = event.target.closest('[data-preview-menu-button]');
    var feedback = event.target.closest('[data-preview-feedback]');
    var stateButton = event.target.closest('[data-preview-state]');
    var dialogButton = event.target.closest('[data-preview-dialog-open]');
    if (menuButton) {
      var menu = menuButton.nextElementSibling;
      var willOpen = menu.hidden;
      closeMenus(menu);
      menu.hidden = !willOpen;
      menuButton.setAttribute('aria-expanded', String(willOpen));
      if (willOpen) menu.querySelector('[role="menuitem"]').focus();
    } else if (feedback) {
      closeMenus();
      showFeedback(feedback.dataset.previewFeedback);
    } else if (stateButton) {
      setState(stateButton.dataset.previewState);
    } else if (dialogButton) {
      dialog.showModal();
      dialog.querySelector('[data-preview-name]').focus();
    } else if (!event.target.closest('[data-preview-menu]')) {
      closeMenus();
    }
  });

  root.querySelector('[data-preview-retry]').addEventListener('click', function () { setState('populated'); });
  root.querySelector('[data-preview-save]').addEventListener('click', function (event) {
    var name = dialog.querySelector('[data-preview-name]');
    if (!name.value.trim()) return;
    event.preventDefault();
    dialog.close();
    showFeedback('Preview saved. Production data was not changed.');
  });
  applySort();
  applyFilters();
}());