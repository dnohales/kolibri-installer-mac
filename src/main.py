import datetime
import gettext
import logging
import os
import subprocess
import sys
import time
import webbrowser


try:
    from urllib2 import urlopen, URLError
except ModuleNotFoundError:
    from urllib.error import URLError
    from urllib.request import urlopen


class LoggerWriter(object):
    def __init__(self, writer):
        self._writer = writer
        self._msg = ''

    def write(self, message):
        self._msg = self._msg + message
        while '\n' in self._msg:
            pos = self._msg.find('\n')
            self._writer(self._msg[:pos])
            self._msg = self._msg[pos+1:]

    def flush(self):
        if self._msg != '':
            self._writer(self._msg)
            self._msg = ''

# initialize logging before loading any third-party modules, as they may cause logging to get configured.
logging.basicConfig(level=logging.DEBUG)

# make sure we add Kolibri's dist folder to the path early on so that we avoid import errors
root_dir = os.path.dirname(os.path.abspath(__file__))
locale_root_dir = os.path.join(root_dir, 'locale')
if root_dir.endswith('src'):
    locale_root_dir = os.path.join(root_dir, '..', 'locale')

if getattr(sys, 'frozen', False):
    if sys.platform == 'darwin':
        # On Mac, included Python packages go into the lib/python3.6
        root_dir = os.path.join(root_dir, "lib", "python3.6")

    # make sure we send all app output to logs as we have no console to view them on.
    sys.stdout = LoggerWriter(logging.debug)
    sys.stderr = LoggerWriter(logging.warning)

kolibri_package_dir = os.path.join(root_dir, "kolibri", "dist")
sys.path.append(kolibri_package_dir)


import pew
import pew.ui

pew.set_app_name("Kolibri")

if pew.ui.platform == "android":
    from jnius import autoclass
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    File = autoclass('java.io.File')
    Timezone = autoclass('java.util.TimeZone')


    # TODO check for storage availibility, allow user to chose sd card or internal
    def get_home_folder():
        kolibri_home_file = PythonActivity.getExternalFilesDir(None)
        return kolibri_home_file.toString()

KOLIBRI_ROOT_URL = 'http://localhost:5000'
os.environ["DJANGO_SETTINGS_MODULE"] = "kolibri.deployment.default.settings.base"

app_data_dir = pew.get_app_files_dir()
os.makedirs(app_data_dir, exist_ok=True)

if pew.ui.platform == "android":
    os.environ["KOLIBRI_HOME"] = get_home_folder()
    os.environ["TZ"] = Timezone.getDefault().getDisplayName()

    logging.info("Home folder: {}".format(os.environ["KOLIBRI_HOME"]))
    logging.info("Timezone: {}".format(os.environ["TZ"]))
elif not 'KOLIBRI_HOME' in os.environ:
    os.environ["KOLIBRI_HOME"] = os.path.join(os.path.expanduser("~"), ".kolibri")


from kolibri.utils.logger import KolibriTimedRotatingFileHandler

log_basename = "kolibri-app.txt"
log_dir = os.path.join(os.environ['KOLIBRI_HOME'], 'logs')
os.makedirs(log_dir, exist_ok=True)
log_filename = os.path.join(log_dir, log_basename)
root_logger = logging.getLogger()
file_handler = KolibriTimedRotatingFileHandler(filename=log_filename, when='midnight', backupCount=30)
root_logger.addHandler(file_handler)

# Since the log files can contain multiple runs, make the first printout very visible to quickly show
# when a new run starts in the log files.
logging.info("")
logging.info("**********************************")
logging.info("*  Kolibri Mac App Initializing  *")
logging.info("**********************************")
logging.info("")
logging.info("Started at: {}".format(datetime.datetime.today()))

languages = None
if sys.platform == 'darwin':
    langs_str = subprocess.check_output('defaults read .GlobalPreferences AppleLanguages | tr -d [:space:]', shell=True).strip()
    languages_base = langs_str[1:-1].decode('utf-8').replace('"', '').replace('-', '_').split(',')
    logging.info("languages= {}".format(languages))
    languages = []
    for lang in languages_base:
        if os.path.exists(os.path.join(locale_root_dir, lang)):
            languages.append(lang)
        elif '_' in lang:
            # make sure we check for base languages in addition to specific dialects.
            languages.append(lang.split('_')[0])

locale_info = {}
try:
    t = gettext.translation('macapp', locale_root_dir, languages=languages, fallback=True)
    locale_info = t.info()
    _ = t.gettext

except Exception as e:
    # Fallback to English and if we fail to find any language catalogs.
    locale_info['language'] = 'en_US'
    def _(text):
        return text
    logging.warning("Error retrieving language: {}".format(repr(e)))

logging.info("Locale info = {}".format(locale_info))


def start_django(port=5000):
    from kolibri.utils.cli import initialize, setup_logging, start

    logging.info("Starting server...")
    setup_logging(debug=False)
    initialize()
    start.callback(port, background=False)


class MenuEventHandler:
    def on_documentation(self):
        webbrowser.open('https://kolibri.readthedocs.io/en/latest/')

    def on_forums(self):
        webbrowser.open('https://community.learningequality.org/')

    def on_new_window(self):
        app = pew.ui.get_app()
        if app:
            window = app.create_kolibri_window(KOLIBRI_ROOT_URL)
            app.windows.append(window)
            window.show()

    def on_close_window(self):
        self.close()

    def on_open_in_browser(self):
        webbrowser.open(self.get_url())

    def on_open_kolibri_home(self):
        subprocess.call(['open', os.environ['KOLIBRI_HOME']])

    def on_back(self):
        self.go_back()

    def on_forward(self):
        self.go_forward()

    def on_reload(self):
        self.reload()

    def on_actual_size(self):
        self.set_zoom_level(2)

    def on_zoom_in(self):
        self.set_zoom_level(self.get_zoom_level() + 1)

    def on_zoom_out(self):
        self.set_zoom_level(self.get_zoom_level() - 1)

    # FIXME: Remove these once the native menu handlers are restored
    def on_redo(self):
        self.webview.Redo()

    def on_undo(self):
        self.webview.Undo()


class KolibriView(pew.ui.WebUIView, MenuEventHandler):
    def __init__(self, *args, **kwargs):
        super(KolibriView, self).__init__(*args, **kwargs)
        MenuEventHandler.__init__(self)

    def shutdown(self):
        """
        By default, WebUIView assumes a single window, to work the same on mobile and desktops.
        Since we allow for multiple windows, make sure we only really shutdown once all windows are
        closed.
        :return:
        """
        app = pew.ui.get_app()
        if app:
            app.windows.remove(self)
            if len(app.windows) > 0:
                # if we still have open windows, don't run shutdown
                return

        super(KolibriView, self).shutdown()


class Application(pew.ui.PEWApp):
    def setUp(self):
        """
        Start your UI and app run loop here.
        """

        # Set loading screen
        lang_id = locale_info['language']
        loader_page = os.path.abspath(os.path.join('assets', '_load-{}.html'.format(lang_id)))
        if not os.path.exists(loader_page):
            lang_id = lang_id.split('-')[0]
            loader_page = os.path.abspath(os.path.join('assets', '_load-{}.html'.format(lang_id)))
        if not os.path.exists(loader_page):
            # if we can't find anything in the given language, default to the English loading page.
            loader_page = os.path.abspath(os.path.join('assets', '_load-{}.html'.format('en_US')))
        self.loader_url = 'file://{}'.format(loader_page)
        self.kolibri_loaded = False

        self.view = self.create_kolibri_window(self.loader_url)

        self.windows = [self.view]

        # start server
        self.server_thread = None
        self.port = 5000
        self.start_server()

        self.load_thread = pew.ui.PEWThread(target=self.wait_for_server)
        self.load_thread.daemon = True
        self.load_thread.start()

        # make sure we show the UI before run completes, as otherwise
        # it is possible the run can complete before the UI is shown,
        # causing the app to shut down early
        self.view.show()
        return 0

    def start_server(self):
        if self.server_thread:
            del self.server_thread

        logging.info("Preparing to start Kolibri server...")
        self.server_thread = pew.ui.PEWThread(target=start_django, kwargs={'port': self.port})
        self.server_thread.daemon = True
        self.server_thread.start()

    def create_kolibri_window(self, url):
        window = KolibriView("Kolibri", url, delegate=self)

        # create menu bar, we do this per-window for cross-platform purposes
        menu_bar = pew.ui.PEWMenuBar()

        file_menu = pew.ui.PEWMenu(_('File'))
        file_menu.add(_('New Window'), handler=window.on_new_window)
        file_menu.add(_('Close Window'), handler=window.on_close_window)
        file_menu.add_separator()
        file_menu.add(_('Open Kolibri Home Folder'), handler=window.on_open_kolibri_home)

        menu_bar.add_menu(file_menu)

        edit_menu = pew.ui.PEWMenu(_('Edit'))
        edit_menu.add(_('Undo'), handler=window.on_undo, shortcut='CTRL+Z')
        edit_menu.add(_('Redo'), handler=window.on_redo, shortcut='CTRL+SHIFT+Z')
        edit_menu.add_separator()
        edit_menu.add(_('Cut'), command='cut', shortcut='CTRL+X')
        edit_menu.add(_('Copy'), command='copy', shortcut='CTRL+C')
        edit_menu.add(_('Paste'), command='paste', shortcut='CTRL+V')
        edit_menu.add(_('Select All'), command='select-all', shortcut='CTRL+A')
        menu_bar.add_menu(edit_menu)

        view_menu = pew.ui.PEWMenu(_('View'))
        view_menu.add(_('Reload'), handler=window.on_reload)
        view_menu.add(_('Actual Size'), handler=window.on_actual_size, shortcut='CTRL+0')
        view_menu.add(_('Zoom In'), handler=window.on_zoom_in, shortcut='CTRL++')
        view_menu.add(_('Zoom Out'), handler=window.on_zoom_out, shortcut='CTRL+-')
        view_menu.add_separator()
        view_menu.add(_('Open in Browser'), handler=window.on_open_in_browser)
        menu_bar.add_menu(view_menu)

        history_menu = pew.ui.PEWMenu(_('History'))
        history_menu.add(_('Back'), handler=window.on_back, shortcut='CTRL+[')
        history_menu.add(_('Forward'), handler=window.on_forward, shortcut='CTRL+]')
        menu_bar.add_menu(history_menu)

        help_menu = pew.ui.PEWMenu(_('Help'))
        help_menu.add(_('Documentation'), handler=window.on_documentation)
        help_menu.add(_('Community Forums'), handler=window.on_forums)
        menu_bar.add_menu(help_menu)

        window.set_menubar(menu_bar)

        return window

    def should_load_url(self, url):
        if url.startswith('http') and not url.startswith(KOLIBRI_ROOT_URL):
            webbrowser.open(url)
            return False

        return True

    def page_loaded(self, url):
        """
        This is a PyEverywhere delegate method to let us know the WebView is ready to use.
        """

        # Make sure that any attempts to use back functionality don't take us back to the loading screen
        # For more info, see: https://stackoverflow.com/questions/8103532/how-to-clear-webview-history-in-android
        if not self.kolibri_loaded and url != self.loader_url:
            # FIXME: Change pew to reference the native webview as webview.native_webview rather than webview.webview
            # for clarity.
            self.kolibri_loaded = True
            self.view.clear_history()

    def wait_for_server(self):
        home_url = KOLIBRI_ROOT_URL
        timeout = 20
        max_retries = 3
        time_spent = 0
        load_retries = 0

        # test url to see if servr has started
        def running():
            try:
                urlopen(home_url)
                return True
            except URLError as e:
                logging.info("Error pinging Kolibri server: {}".format(e))
                # debugging code to check if native cli tools succeed when urlopen fails.
                return subprocess.call(['curl', '-I', home_url]) == 0

        # Tie up this thread until the server is running
        while not running():
            logging.info('Kolibri server not yet started, checking again in one second...')
            time.sleep(1)
            time_spent += 1
            if time_spent > timeout:
                if load_retries < max_retries:
                    logging.warning('Kolibri server not starting, retrying...')
                    # note, we're not actually restarting the server yet, due to some technical issues with that.
                    # leaving the approach in place so we can just drop in the restart code when ready.
                    pew.ui.run_on_main_thread(self.view.evaluate_javascript, 'show_retry()')
                    load_retries += 1
                    time_spent = 0
                else:
                    pew.ui.run_on_main_thread(self.view.evaluate_javascript, 'show_error()')
                    return


        # Check for saved URL, which exists when the app was put to sleep last time it ran
        saved_state = self.view.get_view_state()
        logging.debug('Persisted View State: {}'.format(self.view.get_view_state()))

        if "URL" in saved_state and saved_state["URL"].startswith(home_url):
            pew.ui.run_on_main_thread(self.view.load_url, saved_state["URL"])
            return

        pew.ui.run_on_main_thread(self.view.load_url, home_url)

    def get_main_window(self):
        return self.view

if __name__ == "__main__":
    app = Application()
    app.run()
