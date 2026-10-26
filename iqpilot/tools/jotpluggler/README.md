# Jotpluggler

Launch `./iqpilot/tools/jotpluggler/jotpluggler` to choose a route before plotting.

- **Recent** lists the last 20 successfully loaded routes. Remove only removes an entry from this list; it does not delete recordings.
- **Local Routes** browses folders containing route segment directories such as `dongle|timestamp--0`. Select a route to fill in its name and data directory.
- **Konn3kt** lists devices and recorded drives, with date ranges and filtering. Google, GitHub, Apple, and Microsoft sign-in open your browser and return directly to the app. Authentication is shared with Cabana through `~/.iq/auth.json`.
- Enter a route manually in the fields below the tabs, or choose **Live Stream**.

Use **Open Route** in the menu bar to switch recordings while keeping the current plot layout. **File → Close Route** clears the recording and returns to the chooser. Recent routes persist in `~/.iq/jotpluggler/recent_routes.json`.

Existing command-line routes, layouts, streams, and PNG exports remain supported. Run with `--help` for options.

The route browser verifies your session before listing devices or drives. Missing, invalid, expired, or revoked logins return to the provider chooser. Use **Sign in again** to replace a saved login; network failures offer a retry without discarding your token.

Jotpluggler starts in dark mode. Toggle **Dark mode** in the route chooser, menu bar, or Preferences; the choice is saved immediately in `~/.iq/jotpluggler/settings.json`. Plot backgrounds, axes, panels, and dialogs follow the theme while signal colors stay unchanged.
