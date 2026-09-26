/*
 * app.js — AWS Outposts Migration Intake client-side behaviour.
 *
 * No inline event handlers are used anywhere in this file or in templates.
 * All wiring happens here via addEventListener, preserving CSP compatibility.
 *
 * HTMX handles form submissions, partial updates, and server interactions.
 * This file provides only the thin layer that HTMX cannot: mobile nav toggle
 * and optional HTMX event hooks.
 */

(function () {
  'use strict';

  /**
   * Wire the mobile navigation toggle button.
   *
   * The toggle button (#nav-toggle) flips aria-expanded and adds/removes
   * the nav--open class on the side-nav element (#app-nav), which the CSS
   * uses to slide the panel into view on narrow viewports.
   */
  function initNavToggle() {
    var navToggle = document.getElementById('nav-toggle');
    var nav = document.getElementById('app-nav');

    if (!navToggle || !nav) {
      return;
    }

    navToggle.addEventListener('click', function () {
      var expanded = navToggle.getAttribute('aria-expanded') === 'true';
      navToggle.setAttribute('aria-expanded', String(!expanded));
      nav.classList.toggle('nav--open');
    });

    // Close the nav when the user clicks outside of it on mobile.
    document.addEventListener('click', function (event) {
      if (
        nav.classList.contains('nav--open') &&
        !nav.contains(event.target) &&
        !navToggle.contains(event.target)
      ) {
        navToggle.setAttribute('aria-expanded', 'false');
        nav.classList.remove('nav--open');
      }
    });
  }

  /**
   * Configure HTMX behaviour after swap.
   *
   * Re-focuses the main content region after a full-page navigation swap
   * so keyboard users land in the right place.
   */
  function initHtmxHooks() {
    if (typeof htmx === 'undefined') {
      return;
    }

    document.addEventListener('htmx:afterSettle', function (event) {
      var main = document.getElementById('main-content');
      if (main && event.target === main) {
        main.focus();
      }
    });
  }

  function initEvidenceUpload() {
    var form = document.querySelector('.upload-form');
    var fileInput = document.getElementById('file');
    var selectedFile = document.getElementById('selected-file');
    var submitButton = document.getElementById('upload-submit');

    if (!form || !fileInput || !selectedFile || !submitButton) {
      return;
    }

    fileInput.addEventListener('change', function () {
      selectedFile.textContent = fileInput.files.length
        ? 'Selected: ' + fileInput.files[0].name
        : 'No file selected';
    });

    form.addEventListener('submit', function () {
      submitButton.disabled = true;
      submitButton.textContent = 'Uploading...';
    });
  }

  function initEvidenceDeleteConfirmation() {
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
      form.addEventListener('submit', function (event) {
        if (!window.confirm(form.getAttribute('data-confirm'))) {
          event.preventDefault();
        }
      });
    });
  }

  /* ==================================================================
     Questionnaire (UX-1)
     ================================================================== */

  /**
   * How long to wait after a control loses focus before saving.
   *
   * Tabbing between two fields of the same question fires focusout then
   * focusin in the same task, so a focusin inside the form cancels the
   * pending save. Without that, a two-field editor would post a half-filled
   * payload the response type rejects.
   */
  var SAVE_DELAY_MS = 120;

  /**
   * Serialise a question form for change detection.
   *
   * The concurrency token is excluded on purpose: it changes on every
   * successful save, and including it would make every form look dirty.
   */
  function serialiseForm(form) {
    var parts = [];
    new FormData(form).forEach(function (value, key) {
      if (key === '_row_version') {
        return;
      }
      parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(String(value)));
    });
    return parts.join('&');
  }

  function readJson(response) {
    return response.text().then(function (text) {
      var data = {};
      try {
        data = JSON.parse(text);
      } catch (error) {
        data = {};
      }
      return { ok: response.ok, status: response.status, data: data };
    });
  }

  /**
   * Autosave one question form.
   *
   * The server answers this POST with JSON rather than a redirect and hands
   * back the new revision number. AnswerService compares expected_version
   * against the current *revision number*, so the token has to be written
   * back into the form: re-posting the number the page was rendered with
   * makes the second edit of the same field conflict with the first.
   */
  function initAutosaveForm(form) {
    var code = form.getAttribute('data-question-code');
    var indicator = document.getElementById('q-' + code + '-save');
    var version = form.querySelector('input[name="_row_version"]');
    var card = form.closest('.qx-question');
    var lastSaved = serialiseForm(form);
    var timer = null;

    function setState(state, text) {
      if (!indicator) {
        return;
      }
      indicator.setAttribute('data-state', state);
      indicator.textContent = text;
    }

    function showRetry() {
      if (!indicator) {
        return;
      }
      var retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'qx-retry';
      retry.textContent = 'Retry';
      retry.addEventListener('click', function () {
        save();
      });
      indicator.appendChild(document.createTextNode(' '));
      indicator.appendChild(retry);
    }

    function save() {
      timer = null;
      var payload = serialiseForm(form);
      if (payload === lastSaved) {
        return;
      }
      setState('saving', 'Saving...');
      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { Accept: 'application/json' },
        credentials: 'same-origin'
      })
        .then(readJson)
        .then(function (result) {
          if (!result.ok || !result.data.ok) {
            throw new Error(result.data.error || 'Could not save (' + result.status + ')');
          }
          lastSaved = payload;
          if (
            version &&
            result.data.revision_number !== null &&
            result.data.revision_number !== undefined
          ) {
            version.value = String(result.data.revision_number);
          }
          if (card) {
            card.setAttribute('data-answered', 'true');
          }
          setState('saved', '✓ Saved');
        })
        .catch(function (error) {
          setState('error', error.message || 'Could not save');
          showRetry();
        });
    }

    function schedule() {
      if (timer) {
        window.clearTimeout(timer);
      }
      // Drop out of "Saved" the moment the form is known to be dirty. Leaving
      // the old confirmation up while a new save is pending tells the user —
      // and any test waiting on the indicator — that work is already stored
      // when it is not.
      if (serialiseForm(form) !== lastSaved) {
        setState('saving', 'Saving...');
      }
      timer = window.setTimeout(save, SAVE_DELAY_MS);
    }

    form.addEventListener('focusin', function () {
      if (timer) {
        window.clearTimeout(timer);
        timer = null;
      }
    });
    form.addEventListener('focusout', schedule);
    form.addEventListener('change', schedule);
  }

  function initAutosave(page) {
    Array.prototype.forEach.call(
      page.querySelectorAll('form[data-autosave]'),
      initAutosaveForm
    );
  }

  /**
   * Accept or reject an imported proposal without leaving the question.
   *
   * Posts to the existing candidate-decision routes, which redirect to the
   * bulk coverage page; the redirect is not followed so the user stays where
   * they were, and the section is reloaded to show the new canonical answer.
   */
  function initProposalDecisions(page) {
    Array.prototype.forEach.call(
      page.querySelectorAll('form[data-proposal-decision]'),
      function (form) {
        form.addEventListener('submit', function (event) {
          event.preventDefault();
          var button = form.querySelector('button[type="submit"]');
          if (button) {
            button.disabled = true;
          }
          fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            credentials: 'same-origin',
            redirect: 'manual'
          })
            .then(function (response) {
              if (response.ok || response.type === 'opaqueredirect' || response.status === 0) {
                window.location.reload();
                return;
              }
              throw new Error('That decision could not be recorded (' + response.status + ')');
            })
            .catch(function (error) {
              if (button) {
                button.disabled = false;
              }
              var message = form.parentNode.querySelector('.qx-proposal-error');
              if (!message) {
                message = document.createElement('span');
                message.className = 'qx-proposal-error qx-proposal-blocked';
                form.parentNode.appendChild(message);
              }
              message.textContent = error.message;
            });
        });
      }
    );
  }

  function initPeopleListEditors(page) {
    Array.prototype.forEach.call(
      page.querySelectorAll('.people-list-editor'),
      function (editor) {
        var list = editor.querySelector('[data-collection="people"]');
        var addButton = editor.querySelector('.add-person');
        if (!list || !addButton) {
          return;
        }

        addButton.addEventListener('click', function () {
          var rows = list.querySelectorAll('.person-row');
          var source = rows[rows.length - 1];
          if (!source) {
            return;
          }
          var row = source.cloneNode(true);
          var nextIndex = rows.length;
          row.setAttribute('data-index', String(nextIndex));
          Array.prototype.forEach.call(row.querySelectorAll('input'), function (input) {
            input.name = input.name.replace(/people\[\d+\]/, 'people[' + nextIndex + ']');
            input.value = '';
          });
          list.appendChild(row);
        });

        list.addEventListener('click', function (event) {
          var removeButton = event.target.closest('.remove-person');
          if (!removeButton) {
            return;
          }
          var rows = list.querySelectorAll('.person-row');
          if (rows.length > 1) {
            removeButton.closest('.person-row').remove();
          }
        });
      }
    );
  }

  /**
   * Hide computed questions, which nobody can answer.
   *
   * Server-rendered on by default so the reduction is there before any
   * script runs; the choice is remembered per browser.
   */
  function initDerivedToggle(page) {
    var toggle = document.getElementById('toggle-derived');
    if (!toggle) {
      return;
    }

    function apply() {
      page.classList.toggle('qx-hide-derived', toggle.checked);
    }

    try {
      var stored = window.localStorage.getItem('intake.hideDerived');
      if (stored !== null) {
        toggle.checked = stored === 'true';
      }
    } catch (error) {
      /* Storage unavailable (private mode): fall back to the markup. */
    }
    apply();

    toggle.addEventListener('change', function () {
      apply();
      try {
        window.localStorage.setItem('intake.hideDerived', String(toggle.checked));
      } catch (error) {
        /* Nothing to do: the toggle still works for this page view. */
      }
    });
  }

  function initSkipToUnanswered(page) {
    var button = document.getElementById('skip-to-unanswered');
    if (!button) {
      return;
    }
    button.addEventListener('click', function () {
      var cards = page.querySelectorAll('.qx-question[data-answered="false"]');
      for (var index = 0; index < cards.length; index += 1) {
        var card = cards[index];
        if (card.offsetParent === null) {
          continue; /* Hidden by the derived filter. */
        }
        var disclosure = card.querySelector('details.qx-disclosure');
        if (disclosure) {
          disclosure.open = true;
        }
        card.scrollIntoView({ block: 'center' });
        var field = card.querySelector(
          'input:not([type="hidden"]), select, textarea'
        );
        if (field) {
          field.focus();
        }
        return;
      }
      button.textContent = 'Everything here is answered';
      button.disabled = true;
    });
  }

  function initQuestionnaire() {
    var page = document.getElementById('questionnaire-page');
    if (!page) {
      return;
    }
    initDerivedToggle(page);
    initSkipToUnanswered(page);
    initAutosave(page);
    initProposalDecisions(page);
    initPeopleListEditors(page);
  }

  // Bootstrap on DOM ready.
  document.addEventListener('DOMContentLoaded', function () {
    initNavToggle();
    initHtmxHooks();
    initEvidenceUpload();
    initEvidenceDeleteConfirmation();
    initQuestionnaire();
  });
}());

// WaveUtil client-side filtering
(function () {
  var table = document.querySelector('[data-wave-util-list]');
  if (!table) { return; } // only activates on WaveUtil pages

  function applyFilters() {
    var activeEnvBtn = document.querySelector('.filter-pill--active[data-filter-env]');
    var envFilter = activeEnvBtn ? activeEnvBtn.getAttribute('data-filter-env') : 'ALL';
    var stateSelect = document.querySelector('[data-filter-state]');
    var stateFilter = stateSelect ? stateSelect.value : 'ALL';
    var searchInput = document.querySelector('[data-filter-search]');
    var search = searchInput ? searchInput.value.toLowerCase() : '';

    table.querySelectorAll('tbody tr').forEach(function (row) {
      var envMatch = envFilter === 'ALL' || row.getAttribute('data-environment') === envFilter;
      var stateMatch = stateFilter === 'ALL' || row.getAttribute('data-state') === stateFilter;
      var hostname = row.getAttribute('data-hostname') || '';
      var searchMatch = !search || hostname.toLowerCase().indexOf(search) !== -1;
      row.hidden = !(envMatch && stateMatch && searchMatch);
    });
  }

  document.querySelectorAll('.filter-pill[data-filter-env]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.filter-pill[data-filter-env]').forEach(function (b) {
        b.classList.remove('filter-pill--active');
      });
      btn.classList.add('filter-pill--active');
      applyFilters();
    });
  });

  var stateSelect = document.querySelector('[data-filter-state]');
  if (stateSelect) {
    stateSelect.addEventListener('change', applyFilters);
  }

  var searchInput = document.querySelector('[data-filter-search]');
  if (searchInput) {
    searchInput.addEventListener('input', applyFilters);
  }
}());
