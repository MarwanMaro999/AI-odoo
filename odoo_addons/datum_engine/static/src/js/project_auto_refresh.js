/** @odoo-module **/

/** Automatically refresh a Datum project while a document is being generated. */

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { FormController } from "@web/views/form/form_controller";
import { onWillUnmount } from "@odoo/owl";

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        if (this.props.resModel !== "datum.engagement") {
            return;
        }
        this.orm = useService("orm");
        this.notification = useService("notification");
        this._datumPolling = false;
        this._datumRefreshTimer = setInterval(() => this._refreshDatumProject(), 4000);
        onWillUnmount(() => clearInterval(this._datumRefreshTimer));
    },

    async _refreshDatumProject() {
        const root = this.model.root;
        if (!root || !root.resId || root.isDirty() || this._datumPolling) {
            return;
        }
        this._datumPolling = true;
        try {
            const updates = await this.orm.call("datum.engagement", "action_refresh_ai_status", [[root.resId]]);
            if (!updates.length) {
                return;
            }
            await root.load();
            for (const update of updates) {
                const label = update.skill.replaceAll("-", " ");
                const messages = {
                    queued: `${label} is queued.`,
                    running: `${label} is now being generated.`,
                    succeeded: `${label} is finished and ready to preview.`,
                    failed: `${label} failed${update.failure_code ? `: ${update.failure_code}` : "."}`,
                    cancelled: `${label} was cancelled.`,
                };
                const type = update.state === "failed" ? "danger" : update.state === "succeeded" ? "success" : "info";
                this.notification.add(
                    messages[update.state] || `${label} changed status to ${update.state}.`,
                    { title: update.run_name, type, sticky: update.state === "failed" }
                );
            }
        } catch {
            // The normal Odoo error dialog would be disruptive for a transient poll failure.
        } finally {
            this._datumPolling = false;
        }
    },
});
