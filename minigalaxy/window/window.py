import os
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GdkPixbuf
from minigalaxy.window.login import Login
from minigalaxy.window.gametile import GameTile
from minigalaxy.window.preferences import Preferences
from minigalaxy.window.about import About
from minigalaxy.api import Api
from minigalaxy.config import Config
from minigalaxy.paths import UI_DIR, LOGO_IMAGE_PATH, THUMBNAIL_DIR
from minigalaxy.game import Game


@Gtk.Template.from_file(os.path.join(UI_DIR, "application.ui"))
class Window(Gtk.ApplicationWindow):

    __gtype_name__ = "Window"

    HeaderBar = Gtk.Template.Child()
    header_sync = Gtk.Template.Child()
    header_installed = Gtk.Template.Child()
    header_search = Gtk.Template.Child()
    menu_about = Gtk.Template.Child()
    menu_preferences = Gtk.Template.Child()
    menu_logout = Gtk.Template.Child()
    library = Gtk.Template.Child()

    def __init__(self, name):
        Gtk.ApplicationWindow.__init__(self, title=name)
        self.config = Config()
        self.api = Api(self.config)
        self.show_installed_only = False
        self.search_string = ""
        self.offline = False

        # Set the icon
        icon = GdkPixbuf.Pixbuf.new_from_file(LOGO_IMAGE_PATH)
        self.set_default_icon_list([icon])

        # Create the thumbnails directory
        if not os.path.exists(THUMBNAIL_DIR):
            os.makedirs(THUMBNAIL_DIR)

        # Interact with the API
        self.__authenticate()
        self.HeaderBar.set_subtitle(self.api.get_user_info())
        self.sync_library()

        self.show_all()

    @Gtk.Template.Callback("on_header_sync_clicked")
    def sync_library(self, button=None):
        # Get installed games
        installed_games = self.__get_installed_games()

        # Make a list with the game tiles which are already loaded
        current_tiles = []
        for child in self.library.get_children():
            tile = child.get_children()[0]
            current_tiles.append(tile)

        # Only add games if they aren't already in the list. Otherwise just reload their state
        if not self.offline:
            games = self.api.get_library()
            for game in games:
                not_found = True
                for tile in current_tiles:
                    if tile.game.id == game.id:
                        not_found = False
                        break
                if not_found:
                    # Check if game is already installed
                    installed = False
                    install_dir = ""
                    for installed_game in installed_games:
                        if installed_game["name"] == game.name:
                            print("Found game: {}".format(game.name))
                            installed = True
                            install_dir = installed_game["dir"]
                            break
                    # Create the game tile
                    gametile = GameTile(
                        parent=self,
                        game=game,
                        api=self.api,
                        install_dir=install_dir,
                    )
                    gametile.load_state()
                    self.library.add(gametile)
        else:
            for game in installed_games:
                not_found = True
                for tile in current_tiles:
                    if tile.game.name == game["name"]:
                        not_found = False
                        break
                if not_found:
                    # Create the game tile
                    gametile = GameTile(
                        parent=self,
                        game=Game(game["name"], 0, ""),
                        api=self.api,
                        install_dir=game["dir"],
                    )
                    gametile.load_state()
                    self.library.add(gametile)

        self.sort_library()
        self.filter_library()
        self.library.show_all()

    @Gtk.Template.Callback("on_header_installed_state_set")
    def show_installed_only_triggered(self, switch, state):
        self.show_installed_only = state
        self.library.set_filter_func(self.__filter_library_func)

    @Gtk.Template.Callback("on_header_search_changed")
    def search(self, widget):
        self.search_string = widget.get_text()
        self.library.set_filter_func(self.__filter_library_func)

    @Gtk.Template.Callback("on_menu_preferences_clicked")
    def show_preferences(self, button):
        preferences_window = Preferences(self, self.config)
        preferences_window.run()
        preferences_window.destroy()

    @Gtk.Template.Callback("on_menu_about_clicked")
    def show_about(self, button):
        about_window = About(self)
        about_window.run()
        about_window.destroy()

    @Gtk.Template.Callback("on_menu_logout_clicked")
    def logout(self, button):
        # Unset everything which is specific to this user
        self.HeaderBar.set_subtitle("")
        self.config.unset("username")
        self.config.unset("refresh_token")
        self.hide()

        # Show the login screen
        self.__authenticate()
        self.HeaderBar.set_subtitle(self.api.get_user_info())
        self.sync_library()

        self.show_all()

    def refresh_game_install_states(self, path_changed=False):
        installed_games = self.__get_installed_games()
        for child in self.library.get_children():
            tile = child.get_children()[0]
            if path_changed:
                tile.install_dir = ""
            # Check if game isn't installed already
            for installed_game in installed_games:
                if installed_game["name"] == tile.game.name:
                    tile.install_dir = installed_game["dir"]
                    break
            tile.load_state()
        self.filter_library()

    def filter_library(self):
        self.library.set_filter_func(self.__filter_library_func)

    def __filter_library_func(self, child):
        tile = child.get_children()[0]
        if tile.installed and self.show_installed_only or not self.show_installed_only:
            if self.search_string.lower() in str(tile).lower():
                return True
            else:
                return False
        else:
            return False

    def sort_library(self):
        self.library.set_sort_func(self.__sort_library_func)

    def __sort_library_func(self, child1, child2):
        tile1 = child1.get_children()[0]
        tile2 = child2.get_children()[0]
        return tile2 < tile1

    def __get_installed_games(self) -> dict:
        games = []
        directories = os.listdir(self.config.get("install_dir"))
        for directory in directories:
            full_path = os.path.join(self.config.get("install_dir"), directory)
            if not os.path.isdir(full_path):
                continue
            # Make sure the gameinfo file exists
            gameinfo = os.path.join(full_path, "gameinfo")
            if not os.path.isfile(gameinfo):
                continue
            with open(gameinfo, 'r') as file:
                name = file.readline()
                games.append({'name': name.strip(), 'dir': full_path})
                file.close()
        return games

    """
    The API remembers the authentication token and uses it
    The token is not valid for a long time
    """
    def __authenticate(self):
        url = None
        token = self.config.get("refresh_token")

        authenticated = self.api.authenticate(refresh_token=token, login_code=url)

        while not authenticated:
            login_url = self.api.get_login_url()
            redirect_url = self.api.get_redirect_url()
            login = Login(login_url=login_url, redirect_url=redirect_url, parent=self)
            response = login.run()
            login.hide()
            if response == Gtk.ResponseType.DELETE_EVENT:
                Gtk.main_quit()
                exit(0)
            if response == Gtk.ResponseType.NONE:
                result = login.get_result()
                authenticated = self.api.authenticate(refresh_token=token, login_code=result)

        self.config.set("refresh_token", authenticated)
