frappe.provide("erpnext_extensions.account_explorer.core");

/**
 * Account Explorer event bus.
 *
 * Namespaced events (Wave 3B-0):
 * - page:show              — Desk page became visible again (after first load)
 * - store:change           — ExplorerStore replace/patch ({ state, type, patch })
 * - context:change         — document_scope / analysis_context / presentation changed
 * - summary:loading        — summary request started (store.loading.summary = true)
 * - summary:loaded         — summary response applied ({ data })
 * - workspace:restored     — workspace state hydrated from URL/token (3B-5)
 * - grid:mounted           — summary DataTable mounted
 * - grid:updated           — summary DataTable refreshed
 * - grid:selection_changed — checkbox / row selection changed
 * - grid:column_state_changed — column reorder/remove
 * - grid:destroyed           — summary DataTable destroyed
 * - plugin:registered      — axis plugin registered ({ plugin })
 * - plugin:unregistered    — axis plugin removed ({ id })
 *
 * Loading state is also available via store.get("loading"):
 * - loading.metadata
 * - loading.summary
 */
erpnext_extensions.account_explorer.core.ExplorerEventBus = class ExplorerEventBus {
	constructor() {
		this._handlers = new Map();
	}

	emit(event, payload) {
		const handlers = this._handlers.get(event);
		if (!handlers?.size) {
			return;
		}
		handlers.forEach((handler) => {
			try {
				handler(payload);
			} catch (error) {
				console.error(`[Account Explorer] event handler failed: ${event}`, error);
			}
		});
	}

	subscribe(event, handler) {
		if (!this._handlers.has(event)) {
			this._handlers.set(event, new Set());
		}
		this._handlers.get(event).add(handler);
		return () => this.unsubscribe(event, handler);
	}

	unsubscribe(event, handler) {
		const handlers = this._handlers.get(event);
		if (!handlers) {
			return;
		}
		handlers.delete(handler);
		if (!handlers.size) {
			this._handlers.delete(event);
		}
	}

	get_listener_counts() {
		const by_event = {};
		let total = 0;
		this._handlers.forEach((handlers, event) => {
			by_event[event] = handlers.size;
			total += handlers.size;
		});
		return { total, by_event };
	}
};
