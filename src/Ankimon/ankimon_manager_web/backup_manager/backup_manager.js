/**
 * Ankimon Backup Manager
 *
 * This file powers the "Backup Manager" window in Ankimon. It's the piece
 * of JavaScript that lets players save, restore, and manage backups of
 * their Ankimon save data without ever touching the file system themselves.
 *
 * What it does:
 *
 *  - Shows a list of all your existing backups, each one displayed as a
 *    card with the date and time it was made, your trainer name, your
 *    main Pokémon (and its level), how many Pokémon and items you had,
 *    and how much cash you were carrying.
 *
 *  - Lets you create a brand-new backup of your current save with a single
 *    click, after a quick confirmation popup.
 *
 *  - Lets you restore an old backup. This replaces your current save with
 *    the chosen one and then restarts Anki so the change takes effect.
 *    It always asks for confirmation first, since it's destructive.
 *
 *  - Lets you delete a backup you no longer want, again with a
 *    confirmation popup to prevent accidents.
 *
 *  - Lets you open the folder where backups are stored on your computer,
 *    in case you want to copy them somewhere safe or inspect them
 *    manually.
 *
 *  - Shows friendly toast notifications when something succeeds or fails,
 *    and displays detailed error info (including tracebacks) directly in
 *    the list if the Python side reports a problem.
 *
 * How it talks to the rest of Ankimon:
 *
 *  - It communicates with the Python backend through a QWebChannel bridge
 *    called `backup`. That bridge exposes methods like `getBackups`,
 *    `createBackup`, `restoreBackup`, `deleteBackup`, `openBackupFolder`,
 *    and `restartAnki`.
 *
 *  - There's also a `nav` bridge used to wire up the navigation switcher
 *    and to close the window when the close button is clicked.
 *
 *  - The Python side can call `window.initializeBackupManager(data)` to
 *    push a fresh list of backups into the UI at any time.
 *
 */

(function () {
	'use strict';

	let backupBridge;
	let modalAction = null;

	function money(value) {
		return `$${value ?? 0}`;
	}

	function render(data) {
		if (data && data.error) {
			renderError(data.error);
			return;
		}
		const backups = (data && data.backups) || [];
		const list = document.getElementById('backup-list');
		list.replaceChildren();
		if (!backups.length) {
			list.innerHTML = '<div class="backup-empty">No backups found.</div>';
			return;
		}
		backups.forEach((backup) => {
			const [date = '', time = ''] = String(backup.date || ' ').split(' ');
			const card = document.createElement('article');
			card.className = 'backup-card';
			card.innerHTML = `
				<div class="backup-actions"><button class="restore-btn">Restore Backup</button><button class="delete-btn">Delete Backup</button></div>
				<div class="backup-date"><strong>${date}</strong><span>Time: ${time.replaceAll('-', ':')}</span></div>
				<div class="backup-trainer"><strong>${backup.trainer_name || 'N/A'}</strong><span>${backup.main_pokemon_name || 'N/A'} (Lv. ${backup.main_pokemon_level ?? 'N/A'})</span></div>
				<div class="backup-stat"><span>${backup.pokemon_count || 0} Pokémon</span><span>${backup.item_count || 0} Items</span></div>
				<div class="backup-cash">${money(backup.trainer_cash)}</div>`;
			const actions = card.querySelector('.backup-actions');
			actions.addEventListener('click', (event) => event.stopPropagation());
				actions.querySelector('.restore-btn').addEventListener('click', () => {
				openModal(
					'Restore and Restart',
					'This will replace your current Ankimon save with this backup and restart Anki. Continue?',
					() => restoreBackup(backup.path),
				);
			});
			actions.querySelector('.delete-btn').addEventListener('click', () => {
				openModal('Delete Backup', 'Permanently delete this backup folder?', () => deleteBackup(backup.path));
			});
			list.appendChild(card);
		});
	}

	function refresh() {
		if (backupBridge) {
			backupBridge.getBackups(render);
		} else {
			renderError('Backup Manager is still connecting to Ankimon.');
		}
	}

	function renderError(message) {
		renderFailure(message, null);
	}

	function showToast(message, isError = false) {
		const toast = document.getElementById('toast');
		toast.textContent = message;
		toast.classList.toggle('error', isError);
		toast.classList.add('visible');
		clearTimeout(toast._timer);
		toast._timer = setTimeout(() => toast.classList.remove('visible'), 3000);
	}

	function renderFailure(message, trace) {
		const empty = document.createElement('div');
		empty.className = 'backup-empty backup-error';
		const title = document.createElement('strong');
		title.textContent = message || 'Backup Manager operation failed.';
		empty.appendChild(title);
		if (trace) {
			const details = document.createElement('pre');
			details.textContent = trace;
			empty.appendChild(details);
		}
		const list = document.getElementById('backup-list');
		list.replaceChildren(empty);
	}

	function createBackup() {
		if (!backupBridge) {
			renderError('Backup Manager is still connecting to Ankimon.');
			return;
		}
		openModal('Create New Backup', 'Create and save a backup of your current Ankimon data?', () => {
			backupBridge.createBackup((result) => {
				if (result && result.ok === false) {
					console.error(result.traceback || result.error || 'Could not create backup.');
					showToast('Could not create backup.', true);
					return;
				}
				showToast('Manual backup created successfully!');
				refresh();
			});
		});
	}

	function deleteBackup(path) {
		if (!backupBridge || !path) return;
		backupBridge.deleteBackup(path, (result) => {
			if (result && result.ok === false) {
				console.error(result.traceback || result.error || 'Could not delete backup.');
				showToast(result.error || 'Could not delete backup.', true);
				return;
			}
			showToast('Backup successfully deleted!');
			refresh();
		});
	}

	function restoreBackup(path) {
		if (!backupBridge || !path) {
			showToast('Backup restoration failed. Please try again.', true);
			return;
		}
		backupBridge.restoreBackup(path, (result) => {
			if (!result || result.ok !== true) {
				console.error((result && result.traceback) || (result && result.error) || 'Backup restoration failed.');
				showToast('Backup restoration failed. Please try again.', true);
				return;
			}
			showToast('Backup restoration succeeded! Restarting now...');
			setTimeout(() => {
				backupBridge.restartAnki((restartResult) => {
					if (!restartResult || restartResult.ok !== true) {
						console.error((restartResult && restartResult.error) || 'Anki could not be restarted.');
					}
				});
			}, 500);
		});
	}

	function openModal(title, message, action) {
		document.getElementById('backup-modal-title').textContent = title;
		document.getElementById('backup-modal-message').textContent = message;
		document.getElementById('backup-modal-confirm').textContent = title;
		modalAction = action;
		document.getElementById('backup-modal').classList.remove('hidden');
		document.getElementById('backup-modal-confirm').focus();
	}

	function closeModal() {
		modalAction = null;
		document.getElementById('backup-modal').classList.add('hidden');
	}

	window.initializeBackupManager = render;
	document.addEventListener('DOMContentLoaded', () => {
		document.getElementById('manual-backup-btn').addEventListener('click', createBackup);
		document.getElementById('open-folder-btn').addEventListener('click', () => {
			if (backupBridge) {
				backupBridge.openBackupFolder((result) => {
					if (!result || result.ok === false) {
						renderFailure(
							(result && result.error) || 'Could not open the Ankimon_Backups folder.',
							result && result.traceback,
						);
					}
				});
			} else {
				renderError('Backup Manager is still connecting to Ankimon.');
			}
		});
		document.getElementById('backup-modal-cancel').addEventListener('click', closeModal);
		document.getElementById('backup-modal-confirm').addEventListener('click', () => {
			const action = modalAction;
			closeModal();
			if (action) action();
		});
		document.getElementById('backup-modal').addEventListener('click', (event) => {
			if (event.target.id === 'backup-modal') closeModal();
		});
		document.addEventListener('keydown', (event) => {
			if (event.key === 'Escape') closeModal();
		});
		document.getElementById('close-btn').addEventListener('click', () => {
			if (window.navBridge) window.navBridge.closeWindow();
		});
		new QWebChannel(qt.webChannelTransport, (channel) => {
			backupBridge = channel.objects.backup;
			window.navBridge = channel.objects.nav;
			window.wireNavSwitcher(window.navBridge);
			refresh();
		});
	});
})();
