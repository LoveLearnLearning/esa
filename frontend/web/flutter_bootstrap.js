{{flutter_js}}
{{flutter_build_config}}

_flutter.loader.load({
  onEntrypointLoaded: async (engineInitializer) => {
    const appRunner = await engineInitializer.initializeEngine();
    await appRunner.runApp();
    const loading = document.getElementById('app-loading');
    if (loading) {
      loading.classList.add('is-ready');
      window.setTimeout(() => loading.remove(), 180);
    }
  },
});
