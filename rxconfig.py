import reflex as rx
from reflex_base.plugins.sitemap import SitemapPlugin

config = rx.Config(
    app_name="options_surface_lab",
    app_module_import="options_surface_lab.options_surface_app",
    plugins=[SitemapPlugin()],
)
