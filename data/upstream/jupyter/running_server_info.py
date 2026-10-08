def running_server_info(self, kernel_count: bool = True) -> str:
    """Return the current working directory and the server url information"""
    info = t.cast(str, self.contents_manager.info_string()) + "\n"
    if kernel_count:
        n_kernels = len(self.kernel_manager.list_kernel_ids())
        kernel_msg = trans.ngettext("%d active kernel", "%d active kernels", n_kernels)
        info += kernel_msg % n_kernels
        info += "\n"
    # Format the info so that the URL fits on a single line in 80 char display
    info += _i18n("Jupyter Server {version} is running at:\n{url}").format(
        version=ServerApp.version, url=self.display_url
    )
    if self.gateway_config.gateway_enabled:
        info += (
            _i18n("\nKernels will be managed by the Gateway server running at:\n%s")
            % self.gateway_config.url
        )
    return info
