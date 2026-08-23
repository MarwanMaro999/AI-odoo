{
    "name": "Datum Engine",
    "version": "17.0.1.0.0",
    "summary": "Internal AI document production and review workflow",
    "license": "LGPL-3",
    "depends": ["base", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/cron.xml",
        "views/datum_engine_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "datum_engine/static/src/js/project_auto_refresh.js",
        ],
    },
    "application": True,
    "installable": True,
}
