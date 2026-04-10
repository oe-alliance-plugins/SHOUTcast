#
#  SHOUTcast E2
#
#  $Id$
#
#  Coded by Dr.Best (c) 2010
#  Support: www.dreambox-tools.info
#
#  This plugin is licensed under the Creative Commons
#  Attribution-NonCommercial-ShareAlike 3.0 Unported
#  License. To view a copy of this license, visit
#  http://creativecommons.org/licenses/by-nc-sa/3.0/ or send a letter to Creative
#  Commons, 559 Nathan Abbott Way, Stanford, California 94305, USA.
#
#  Alternatively, this plugin may be distributed and executed on hardware which
#  is licensed by Dream Multimedia GmbH.

#  This plugin is NOT free software. It is open source, you are allowed to
#  modify it (if you keep the license), but it may not be commercially
#  distributed other than under the conditions noted above.
#

from os import path, mkdir, unlink
from re import compile, findall, S, I
from requests import get, exceptions
from skin import parameters
from urllib.parse import quote, urlparse
from twisted.internet import reactor
from twisted.web.client import HTTPClientFactory
from twisted.internet.reactor import callInThread
from xml.etree.ElementTree import fromstring
from enigma import eServiceReference, eListboxPythonMultiContent, eListbox, gFont, RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_CENTER, getDesktop, iServiceInformation, eTimer, eConsoleAppContainer, ePicLoad
from Components.Label import Label
from Components.Input import Input
from Components.Pixmap import Pixmap
from Components.FileList import FileList
from Components.ActionMap import ActionMap
from Components.SystemInfo import SystemInfo
from Components.GUIComponent import GUIComponent
from Components.ConfigList import ConfigListScreen
from Components.Sources.StaticText import StaticText
from Components.config import config, ConfigSubsection, ConfigSelection, ConfigDirectory, ConfigYesNo, Config, ConfigInteger, ConfigSubList, ConfigText, ConfigNumber, getConfigListEntry, configfile
from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Screens.InfoBar import InfoBar
from Screens.InputBox import InputBox
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Tools.Directories import fileExists
from . import _  # for localized messages

coverfiles = ("/tmp/.cover.ping", "/tmp/.cover.pong")
containerStreamripper = None
config.plugins.shoutcast = ConfigSubsection()
config.plugins.shoutcast.showcover = ConfigYesNo(default=False)
config.plugins.shoutcast.showinextensions = ConfigYesNo(default=False)
config.plugins.shoutcast.streamingrate = ConfigSelection(default="0", choices=[("0", _("All")), ("64", _(">= 64 kbps")), ("128", _(">= 128 kbps")), ("192", _(">= 192 kbps")), ("256", _(">= 256 kbps"))])
config.plugins.shoutcast.reloadstationlist = ConfigSelection(default="0", choices=[("0", _("Off")), ("1", _("every minute")), ("3", _("every three minutes")), ("5", _("every five minutes"))])
config.plugins.shoutcast.dirname = ConfigDirectory(default="/media/hdd/streamripper/")
config.plugins.shoutcast.riptosinglefile = ConfigYesNo(default=False)
config.plugins.shoutcast.createdirforeachstream = ConfigYesNo(default=True)
config.plugins.shoutcast.addsequenceoutputfile = ConfigYesNo(default=False)
config.plugins.shoutcast.cover_width = ConfigNumber(default=200)
config.plugins.shoutcast.cover_height = ConfigNumber(default=300)

devid = "fa1jo93O_raeF0v9"

_VALID_URI = compile(br"\A[\x21-\x7e]+\Z")


def ensure_binary(s):
	if isinstance(s, str):
		return s.encode("utf-8")
	return s


def ensure_str(s):
	if isinstance(s, bytes):
		return s.decode("utf-8")
	return s


class SHOUTcastGenre:
	def __init__(self, name="", id=0, haschilds="false", parentid=0, opened="false"):
		self.name = name
		self.id = id
		self.haschilds = haschilds
		self.parentid = parentid
		self.opened = opened


class SHOUTcastStation:
	def __init__(self, name="", mt="", id="", br="", genre="", ct="", lc="", ml="", nsc="", cst=""):
		self.name = name.replace("- a SHOUTcast.com member station", "")
		self.mt = mt
		self.id = id
		self.br = br
		self.genre = genre
		self.ct = ct
		self.lc = lc
		self.ml = ml
		self.nsc = nsc
		self.cst = cst


class Favorite:
	def __init__(self, config_item=None):
		self.config_item = config_item


class MYHTTPClientFactory(HTTPClientFactory):
	def __init__(self, url, method=b'GET', postdata=None, headers=None,
			agent=b"Mozilla/5.0 (Windows NT 6.1; rv:17.0) Gecko/20100101 Firefox/17.0", timeout=0, cookies=None,
			follow_redirect=1, last_modified=None, etag=None):
		HTTPClientFactory.__init__(self, url, method=method, postdata=postdata,
		headers=headers, agent=agent, timeout=timeout, cookies=cookies, followRedirect=follow_redirect)

	def clientConnectionLost(self, connector, reason):
		lostreason = (b"Connection was closed cleanly" in vars(reason))
		if lostreason:
			print(f"[SHOUTcast] Lost connection, reason: {reason} ,trying to reconnect!")
			connector.connect()

	def clientConnectionFailed(self, connector, reason):
		print(f"[SHOUTcast] connection failed, reason: {reason},trying to reconnect!")
		connector.connect()


def send_url_command(url, timeout=60, *args, **kwargs):
	parsed = urlparse(url)
	scheme = parsed.scheme
	host = parsed.hostname
	port = parsed.port or (443 if scheme == 'https' else 80)
	path = parsed.path or '/'
	url = ensure_binary(url)
	factory = MYHTTPClientFactory(url, *args, **kwargs)
	print(f"scheme={scheme} host={host} port={port} path={path}\n")
	reactor.connectTCP(host, port, factory, timeout=timeout)
	return factory.deferred


def main(session, **kwargs):
	session.open(SHOUTcastWidget)


def Plugins(**kwargs):
	plist = [PluginDescriptor(name="SHOUTcast", description=_("listen to shoutcast internet-radio"), where=[PluginDescriptor.WHERE_PLUGINMENU], icon="plugin.png", fnc=main)]  # always show in plugin menu
	if config.plugins.shoutcast.showinextensions.value:
		plist.append(PluginDescriptor(name="SHOUTcast", description=_("listen to shoutcast internet-radio"), where=[PluginDescriptor.WHERE_EXTENSIONSMENU], fnc=main))
	return plist


class SHOUTcastWidget(Screen):

	GENRELIST = 0
	STATIONLIST = 1
	FAVORITELIST = 2
	SEARCHLIST = 3

	STREAMRIPPER_BIN = '/usr/bin/streamripper'

	SC = 'http://api.shoutcast.com'
	SCY = 'http://yp.shoutcast.com'

	FAVORITE_FILE_DEFAULT = '/usr/lib/enigma2/python/Plugins/Extensions/SHOUTcast/favorites'
	FAVORITE_FILE_OLD = '/usr/lib/enigma2/python/Plugins/Extensions/SHOUTcast/favorites.user'
	FAVORITE_FILE = '/etc/enigma2/SHOUTcast.favorites'

	sz_w = getDesktop(0).size().width() - 90
	sz_h = getDesktop(0).size().height() - 95
	print(f"[SHOUTcast] desktop size {sz_w + 90}x{sz_h + 100}\n")
	if sz_h < 500:
		sz_h += 4
	skin = """
		<screen name="SHOUTcastWidget" position="center,65" title="SHOUTcast" size="%d,%d">
			<ePixmap position="5,0" zPosition="4" size="140,40" pixmap="skin_default/buttons/red.png" transparent="1" alphatest="on" />
			<ePixmap position="150,0" zPosition="4" size="140,40" pixmap="skin_default/buttons/green.png" transparent="1" alphatest="on" />
			<ePixmap position="295,0" zPosition="4" size="140,40" pixmap="skin_default/buttons/yellow.png" transparent="1" alphatest="on" />
			<ePixmap position="440,0" zPosition="4" size="140,40" pixmap="skin_default/buttons/blue.png" transparent="1" alphatest="on" />
			<ePixmap pixmap="skin_default/buttons/key_menu.png" position="585,10" zPosition="0" size="35,25" alphatest="on" />
			<widget render="Label" source="key_red" position="5,0" size="140,40" zPosition="5" valign="center" halign="center" backgroundColor="red" font="Regular;20" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-1,-1" />
			<widget render="Label" source="key_green" position="150,0" size="140,40" zPosition="5" valign="center" halign="center" backgroundColor="red" font="Regular;20" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-1,-1" />
			<widget render="Label" source="key_yellow" position="295,0" size="140,40" zPosition="5" valign="center" halign="center" backgroundColor="red" font="Regular;20" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-1,-1" />
			<widget render="Label" source="key_blue" position="440,0" size="140,40" zPosition="5" valign="center" halign="center" backgroundColor="red" font="Regular;20" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-1,-1" />
			<widget name="headertext" position="5,47" zPosition="1" size="%d,23" font="Regular;20" transparent="1"  backgroundColor="#00000000"/>
			<widget name="statustext" position="5,240" zPosition="1" size="%d,90" font="Regular;20" halign="center" valign="center" transparent="0"  backgroundColor="#00000000"/>
			<widget name="list" position="5,80" zPosition="2" size="%d,%d" scrollbarMode="showOnDemand" transparent="0"  backgroundColor="#00000000"/>
			<widget name="titel" position="115,%d" zPosition="1" size="%d,40" font="Regular;18" transparent="1"  backgroundColor="#00000000"/>
			<widget name="station" position="115,%d" zPosition="1" size="%d,40" font="Regular;18" transparent="1"  backgroundColor="#00000000"/>
			<widget name="console" position="115,%d" zPosition="1" size="%d,40" font="Regular;18" transparent="1"  backgroundColor="#00000000"/>
			<widget name="cover" zPosition="2" position="5,%d" size="102,110" alphatest="blend" />
			<ePixmap position="%d,41" zPosition="4" size="120,35" pixmap="/usr/lib/enigma2/python/Plugins/Extensions/SHOUTcast/shoutcast-logo1-fs8.png" transparent="1" alphatest="on" />
		</screen>""" % (
			sz_w, sz_h,  # size
			sz_w - 135,  # size headertext
			sz_w - 100,  # size statustext
			sz_w - 10, sz_h - 205,  # size list
			sz_h - 105,  # position titel
			sz_w - 125,  # size titel
			sz_h - 70,  # position station
			sz_w - 125,  # size station
			sz_h - 25,  # position console
			sz_w - 125,  # size console
			sz_h - 105,  # position cover
			sz_w - 125,  # position logo
			)

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self.oldtitle = None
		self.currentcoverfile = 0
		self.currentGoogle = None
		self.nextGoogle = None
		self.currPlay = None
		self.CurrentService = self.session.nav.getCurrentlyPlayingServiceReference()
		self.session.nav.stopService()
		self.session.nav.event.append(self.__event)
		self["cover"] = Cover()
		self["key_red"] = StaticText(_("Record"))
		self["key_green"] = StaticText(_("Genres"))
		self["key_yellow"] = StaticText(_("Stations"))
		self["key_blue"] = StaticText(_("Favorites"))
		self.mode = self.FAVORITELIST
		self["list"] = SHOUTcastList()
		self["list"].connectSelChanged(self.onSelectionChanged)
		self["statustext"] = Label(_("Getting SHOUTcast genre list..."))
		self["actions"] = ActionMap(["WizardActions", "DirectionActions", "ColorActions", "EPGSelectActions"],
		{
			"ok": self.ok_pressed,
			"back": self.close,
			"menu": self.menu_pressed,
			"red": self.red_pressed,
			"green": self.green_pressed,
			"yellow": self.yellow_pressed,
			"blue": self.blue_pressed,
			"nextBouquet": self.nextPipService,
			"prevBouquet": self.prevPipService
		}, -1)
		self.station_list = []
		self.station_list_idx = 0
		self.genre_list = []
		self.genre_list_idx = 0
		self.favorite_list = []
		self.favorite_list_idx = 0

		self.favoriteConfig = Config()
		if path.exists(self.FAVORITE_FILE):
			self.favoriteConfig.loadFromFile(self.FAVORITE_FILE)
		elif path.exists(self.FAVORITE_FILE_OLD):
			self.favoriteConfig.loadFromFile(self.FAVORITE_FILE_OLD)
		else:
			self.favoriteConfig.loadFromFile(self.FAVORITE_FILE_DEFAULT)
		self.favoriteConfig.entriescount = ConfigInteger(0)
		self.favoriteConfig.Entries = ConfigSubList()
		self.initFavouriteConfig()
		self.stationListXML = ""
		self["titel"] = Label()
		self["station"] = Label()
		self["headertext"] = Label()
		self["console"] = Label()
		self.headerTextString = ""
		self.stationListHeader = ""
		self.tunein = ""
		self.searchSHOUTcastString = ""
		self.currentStreamingURL = ""
		self.currentStreamingStation = ""
		self.stationListURL = ""
		self.onClose.append(self.__onClose)
		self.onLayoutFinish.append(self.getFavoriteList)

		self.reloadStationListTimer = eTimer()
		self.reloadStationListTimer.timeout.get().append(self.reloadStationListTimerTimeout)
		self.reloadStationListTimerVar = int(config.plugins.shoutcast.reloadstationlist.value)

		self.visible = True

		global containerStreamripper
		if containerStreamripper is None:
			containerStreamripper = eConsoleAppContainer()

		containerStreamripper.dataAvail.append(self.streamripperDataAvail)
		containerStreamripper.appClosed.append(self.streamripperClosed)

		if containerStreamripper.running():
			self["key_red"].setText(_("Stop record"))
			# just to hear to recording music when starting the plugin...
			self.currentStreamingStation = _("Recording stream station")
			self.playServiceStream("http://localhost:9191")

		if InfoBar.instance is not None:
			self.servicelist = InfoBar.instance.servicelist
		else:
			self.servicelist = None
		slist = self.servicelist
		if slist:
			try:
				self.pipZapAvailable = slist.dopipzap
			except Exception:
				self.pipZapAvailable = None

	def openServiceList(self):
		if self.pipZapAvailable is None:
			return
		if self.servicelist and self.servicelist.dopipzap:
			self.session.execDialog(self.servicelist)
		else:
			self.showWindow()

	def activatePiP(self):
		if self.pipZapAvailable is None:
			return
		if SystemInfo.get("NumVideoDecoders", 1) > 1 and InfoBar.instance is not None:
			modeslist = []
			keyslist = []
			if InfoBar.pipShown(InfoBar.instance):
				slist = self.servicelist
				if slist:
					try:
						if slist.dopipzap:
							modeslist.append((_("Zap focus to main screen"), "pipzap"))
						else:
							modeslist.append((_("Zap focus to Picture in Picture"), "pipzap"))
						keyslist.append('red')
					except Exception:
						pass
				modeslist.append((_("Move Picture in Picture"), "move"))
				keyslist.append('green')
				modeslist.append((_("Disable Picture in Picture"), "stop"))
				keyslist.append('blue')
			else:
				if len(self.currentStreamingURL) == 0:
					self.session.open(MessageBox, _("First play streaming!"), MessageBox.TYPE_INFO, timeout=5)
					return
				modeslist.append((_("Activate Picture in Picture"), "start"))
				keyslist.append('blue')
			dlg = self.session.openWithCallback(self.pipAnswerConfirmed, ChoiceBox, title=_("Choose action:"), list=modeslist, keys=keyslist)
			dlg.setTitle(_("Menu PiP"))

	def pipAnswerConfirmed(self, answer):
		answer = answer and answer[1]
		if answer is None:
			return
		if answer == "pipzap":
			try:
				InfoBar.togglePipzap(InfoBar.instance)
				if self.visible:
					self.hideWindow()
			except Exception:
				pass
		elif answer == "move":
			if InfoBar.instance is not None:
				InfoBar.movePiP(InfoBar.instance)
		elif answer == "stop":
			if InfoBar.instance is not None and InfoBar.pipShown(InfoBar.instance):
				slist = self.servicelist
				try:
					if slist and slist.dopipzap:
						slist.togglePipzap()
				except Exception:
					pass
				if hasattr(self.session, 'pip'):
					del self.session.pip
				self.session.pipshown = False
		elif answer == "start":
			prev_playingref = self.session.nav.getCurrentlyPlayingServiceReference()
			if prev_playingref:
				self.session.nav.currentlyPlayingServiceReference = None
			InfoBar.showPiP(InfoBar.instance)
			if self.visible:
				self.hideWindow()
			if prev_playingref:
				self.session.nav.currentlyPlayingServiceReference = prev_playingref
			slist = self.servicelist
			if slist:
				try:
					if not slist.dopipzap and hasattr(self.session, 'pip'):
						InfoBar.togglePipzap(InfoBar.instance)
				except Exception:
					pass

	def nextPipService(self):
		if self.pipZapAvailable is None:
			return
		if self.visible:
			return
		try:
			slist = self.servicelist
			if slist and slist.dopipzap:
				if slist.inBouquet():
					prev = slist.getCurrentSelection()
					if prev:
						prev = prev.toString()
						while True:
							if config.usage.quickzap_bouquet_change.value and slist.atEnd():
								slist.nextBouquet()
							else:
								slist.moveDown()
							cur = slist.getCurrentSelection()
							if not cur or (not (cur.flags & 64)) or cur.toString() == prev:
								break
				else:
					slist.moveDown()
				slist.zap(enable_pipzap=True)
		except Exception:
			pass

	def prevPipService(self):
		if self.pipZapAvailable is None:
			return
		if self.visible:
			return
		try:
			slist = self.servicelist
			if slist and slist.dopipzap and slist.inBouquet():
				prev = slist.getCurrentSelection()
				if prev:
					prev = prev.toString()
					while True:
						if config.usage.quickzap_bouquet_change.value:
							if slist.atBegin():
								slist.prevBouquet()
						slist.moveUp()
						cur = slist.getCurrentSelection()
						if not cur or (not (cur.flags & 64)) or cur.toString() == prev:
							break
				else:
					slist.moveUp()
				slist.zap(enable_pipzap=True)
		except Exception:
			pass

	def streamripperClosed(self, retval):
		if retval == 0:
			self["console"].setText("")
		self["key_red"].setText(_("Record"))

	def streamripperDataAvail(self, data):
		data = ensure_str(data)
		s_data = data.replace('\n', '')
		self["console"].setText(s_data)

	def stopReloadStationListTimer(self):
		if self.reloadStationListTimer.isActive():
			self.reloadStationListTimer.stop()

	def reloadStationListTimerTimeout(self):
		self.stopReloadStationListTimer()
		if self.mode == self.STATIONLIST:
			# print(f"[SHOUTcast] reloadStationList: {self.stationListURL}")
			send_url_command(self.stationListURL, None, 10).addCallback(self.callbackStationList).addErrback(self.callbackStationListError)

	def InputBoxStartRecordingCallback(self, return_value=None):
		if return_value:
			recording_length = int(return_value) * 60
			if not path.exists(config.plugins.shoutcast.dirname.value):
				try:
					mkdir(config.plugins.shoutcast.dirname.value)
				except OSError:
					self.session.open(MessageBox, _("Error create directory %s!") % config.plugins.shoutcast.dirname.value, MessageBox.TYPE_ERROR, timeout=10)
					return
			args = []
			args.append(self.currentStreamingURL)
			args.append('-d')
			args.append(config.plugins.shoutcast.dirname.value)
			args.append('-r')
			args.append('9191')
			if recording_length != 0:
				args.append('-l')
				args.append("%d" % int(recording_length))
			if config.plugins.shoutcast.riptosinglefile.value:
				args.append('-a')
				args.append('-A')
			if not config.plugins.shoutcast.createdirforeachstream.value:
				args.append('-s')
			if config.plugins.shoutcast.addsequenceoutputfile.value:
				args.append('-q')
			if not fileExists(self.STREAMRIPPER_BIN):
				self.session.open(MessageBox, _("streamripper not installed!"), MessageBox.TYPE_ERROR, timeout=10)
				return
			cmd = [self.STREAMRIPPER_BIN, self.STREAMRIPPER_BIN] + args
			containerStreamripper.execute(*cmd)
			self["key_red"].setText(_("Stop record"))

	def deleteRecordingConfirmed(self, val):
		if val:
			containerStreamripper.sendCtrlC()

	def red_pressed(self):
		if self.visible:
			if containerStreamripper.running():
				self.session.openWithCallback(self.deleteRecordingConfirmed, MessageBox, _("Do you really want to stop the recording?"))
			else:
				if len(self.currentStreamingURL) != 0:
					self.session.openWithCallback(self.InputBoxStartRecordingCallback, InputBox, windowTitle=_("Recording length"), title=_("Enter in minutes (0 means unlimited)"), text="0", type=Input.NUMBER)
				else:
					self.session.open(MessageBox, _("Only running streamings can be recorded!"), type=MessageBox.TYPE_INFO, timeout=20)
		else:
			if self.pipZapAvailable is not None and SystemInfo.get("NumVideoDecoders", 1) > 1:
				self.activatePiP()
			else:
				self.showWindow()

	def green_pressed(self):
		if self.visible:
			if self.mode != self.GENRELIST:
				self.stopReloadStationListTimer()
				self.mode = self.GENRELIST
			if not self.genre_list:
				self.getGenreList()
			else:
				self.showGenreList()
		else:
			self.showWindow()

	def yellow_pressed(self):
		if self.visible:
			if self.mode != self.STATIONLIST:
				if len(self.station_list):
					self.mode = self.STATIONLIST
					self.headerTextString = _("SHOUTcast station list for %s") % self.stationListHeader
					self["headertext"].setText(self.headerTextString)
					self["list"].setMode(self.mode)
					self["list"].setList([(x,) for x in self.station_list])
					self["list"].moveToIndex(self.station_list_idx)
					if self.reloadStationListTimerVar != 0:
						self.reloadStationListTimer.start(60000 * self.reloadStationListTimerVar)
		else:
			self.showWindow()

	def blue_pressed(self):
		if self.visible:
			if self.mode != self.FAVORITELIST:
				self.stopReloadStationListTimer()
				self.getFavoriteList(self.favorite_list_idx)
		else:
			if self.pipZapAvailable is not None and SystemInfo.get("NumVideoDecoders", 1) > 1:
				self.openServiceList()
			else:
				self.showWindow()

	def getFavoriteList(self, favoriteListIndex=0):
		self["statustext"].setText("")
		self.headerTextString = _("Favorite list")
		self["headertext"].setText(self.headerTextString)
		self.mode = self.FAVORITELIST
		self["list"].setMode(self.mode)
		favoriteList = []
		for item in self.favoriteConfig.Entries:
			favoriteList.append(Favorite(config_item=item))
		self["list"].setList([(x,) for x in favoriteList])
		if len(favoriteList):
			self["list"].moveToIndex(favoriteListIndex)
		self["list"].show()

	def getGenreList(self, genre="all", id=0):
		self["headertext"].setText("")
		self["statustext"].setText(_(f"Getting SHOUTcast genre list for {genre}..."))
		self["list"].hide()
		if len(devid) > 8:
			url = self.SC + f"/genre/secondary?parentid={id}&k={devid}&f=xml"
		else:
			url = ""
			# url = "http://207.200.98.1/sbin/newxml.phtml"  # what's that? what for?
		if url:
			send_url_command(url, None, 10).addCallback(self.callbackGenreList).addErrback(self.callbackGenreListError)

	def callbackGenreList(self, xmlstring):
		xmlstring = ensure_str(xmlstring)
		self["headertext"].setText(_("SHOUTcast genre list"))
		self.genre_list_idx = 0
		self.mode = self.GENRELIST
		self.genre_list = self.fillGenreList(xmlstring)
		self["statustext"].setText("")
		if not len(self.genre_list):
			self["statustext"].setText(_("Got 0 genres. Could be a network problem.\nPlease try again..."))
		else:
			self.showGenreList()

	def callbackGenreListError(self, error=None):
		if error is not None:
			try:
				self["list"].hide()
				self["statustext"].setText(_("%s\nPress green-button to try again...") % str(error.getErrorMessage()))
			except Exception:
				pass

	def fillGenreList(self, xmlstring):
		genreList = []
		# print(f"[SHOUTcast] fillGenreList\n{xmlstring}")
		try:
			root = fromstring(xmlstring)
		except Exception:
			return []
		data = root.find("data")
		if data is None:
			print("[SHOUTcast] could not find data tag, assume flat listing\n")
			return [SHOUTcastGenre(name=childs.get("name")) for childs in root.findall("genre")]
		for glist in data.findall("genrelist"):
			for childs in glist.findall("genre"):
				gn = childs.get("name")
				gid = childs.get("id")
				gparentid = childs.get("parentid")
				ghaschilds = childs.get("haschildren")
				# print(f"[SHOUTcast] Genre {gn} id={gid} parent={gparentid} haschilds={ ghaschilds}\n")
				genreList.append(SHOUTcastGenre(name=gn, id=gid, parentid=gparentid, haschilds=ghaschilds))
				if ghaschilds == "true":
					for childlist in childs.findall("genrelist"):
						for genre in childlist.findall("genre"):
							gn = genre.get("name")
							gid = genre.get("id")
							gparentid = genre.get("parentid")
							ghaschilds = genre.get("haschildren")
							# print(f"[SHOUTcast]   Genre {gn} id=[gid] parent={gparentid} haschilds={ghaschilds}\n")
							genreList.append(SHOUTcastGenre(name=gn, id=gid, parentid=gparentid, haschilds=ghaschilds))
		return genreList

	def showGenreList(self):
		self["headertext"].setText(_("SHOUTcast genre list"))
		self["list"].setMode(self.mode)
		self["list"].setList([(x,) for x in self.genre_list])
		self["list"].moveToIndex(self.genre_list_idx)
		self["list"].show()

	def onSelectionChanged(self):
		pass
		# till I find a better solution
#		if self.mode == self.STATIONLIST:
#			self.station_list_idx = self["list"].getCurrentIndex()
#		elif self.mode == self.FAVORITELIST:
#			self.favorite_list_idx = self["list"].getCurrentIndex()
#		elif self.mode == self.GENRELIST:
#			self.genre_list_idx = self["list"].getCurrentIndex()

	def ok_pressed(self):
		if self.visible:
			sel = None
			try:
				sel = self["list"].l.getCurrentSelection()[0]
			except Exception:
				return
			if sel is None:
				return
			else:
				if self.mode == self.GENRELIST:
					self.genre_list_idx = self["list"].getCurrentIndex()
					self.getStationList(sel.name)
				elif self.mode == self.STATIONLIST:
					self.station_list_idx = self["list"].getCurrentIndex()
					self.stopPlaying()
					if len(devid) > 8:
						url = self.SCY + f"/sbin/tunein-station.pls?id={sel.id}"
					self["list"].hide()
					self["statustext"].setText(_("Getting streaming data from\n%s") % sel.name)
					self.currentStreamingStation = sel.name
					send_url_command(url, None, 10).addCallback(self.callbackPLS).addErrback(self.callbackStationListError)
				elif self.mode == self.FAVORITELIST:
					self.favorite_list_idx = self["list"].getCurrentIndex()
					if sel.config_item.type.value == "url":
						self.stopPlaying()
						self["headertext"].setText(self.headerTextString)
						self.currentStreamingStation = sel.config_item.name.value
						self.playServiceStream(sel.config_item.text.value)
					elif sel.config_item.type.value == "pls":
						self.stopPlaying()
						url = sel.config_item.text.value
						self["list"].hide()
						self["statustext"].setText(_("Getting streaming data from\n%s") % sel.config_item.name.value)
						self.currentStreamingStation = sel.config_item.name.value
						send_url_command(url, None, 10).addCallback(self.callbackPLS).addErrback(self.callbackStationListError)
					elif sel.config_item.type.value == "genre":
						self.getStationList(sel.config_item.name.value)
				elif self.mode == self.SEARCHLIST and self.searchSHOUTcastString != "":
					self.searchSHOUTcast(self.searchSHOUTcastString)
		else:
			self.showWindow()

	def stopPlaying(self):
		self.currentStreamingURL = ""
		self.currentStreamingStation = ""
		self["headertext"].setText("")
		self["titel"].setText("")
		self["station"].setText("")
		self.summaries.setText("")
		if config.plugins.shoutcast.showcover.value:
			self["cover"].doHide()
		self.session.nav.stopService()

	def callbackPLS(self, result):
		result = ensure_str(result)
		self["headertext"].setText(self.headerTextString)
		found = False
		parts = result.split("\n")
		for lines in parts:
			if lines.find("File1=") != -1:
				line = lines.split("File1=")
				found = True
				self.playServiceStream(line[-1].rstrip().strip())

		if found:
			self["statustext"].setText("")
			self["list"].show()
		else:
			self.currentStreamingStation = ""
			self["statustext"].setText(_("No streaming data found..."))
			self["list"].show()

	def getStationList(self, genre):
		self.stationListHeader = _("genre %s") % genre
		self.headerTextString = _("SHOUTcast station list for %s") % self.stationListHeader
		self["headertext"].setText("")
		self["statustext"].setText(_("Getting %s") % self.headerTextString)
		self["list"].hide()
		if len(devid) > 8:
			self.stationListURL = f"{self.SC}/station/advancedsearch&f=xml&k={devid}&search={quote(genre)}"
		else:
			self.stationListURL = ""
		#	self.stationListURL = f"http://207.200.98.1/sbin/newxml.phtml?genre={quote(genre)}"  # what's that? what for?
		self.station_list_idx = 0
		send_url_command(self.stationListURL, None, 10).addCallback(self.callbackStationList).addErrback(self.callbackStationListError)

	def callbackStationList(self, xmlstring):
		xmlstring = ensure_str(xmlstring)
		self.searchSHOUTcastString = ""
		self.stationListXML = xmlstring
		self["headertext"].setText(self.headerTextString)
		self.mode = self.STATIONLIST
		self["list"].setMode(self.mode)
		self.station_list = self.fillStationList(xmlstring)
		self["statustext"].setText("")
		self["list"].setList([(x,) for x in self.station_list])
		if len(self.station_list):
			self["list"].moveToIndex(self.station_list_idx)
		self["list"].show()
		if self.reloadStationListTimerVar != 0:
			self.reloadStationListTimer.start(1000 * 60)

	def fillStationList(self, xmlstring):
		stationList = []
		try:
			root = fromstring(xmlstring)
		except Exception:
			return []
		config_bitrate = int(config.plugins.shoutcast.streamingrate.value)
		data = root.find("data")
		if data is None:
			print("[SHOUTcast] could not find data tag\n")
			return []
		for slist in data.findall("stationlist"):
			for childs in slist.findall("tunein"):
				self.tunein = childs.get("base")
			for childs in slist.findall("station"):
				try:
					bitrate = int(childs.get("br"))
				except Exception:
					bitrate = 0
				if bitrate >= config_bitrate:
					stationList.append(SHOUTcastStation(name=childs.get("name"),
									mt=childs.get("mt"), id=childs.get("id"), br=childs.get("br"),
									genre=childs.get("genre"), ct=childs.get("ct"), lc=childs.get("lc"), ml=childs.get("ml"), nsc=childs.get("nsc"),
									cst=childs.get("cst")))
		return stationList

	def menu_pressed(self):
		if not self.visible:
			self.showWindow()
		options = [(_("Config"), self.config), (_("Search"), self.search), ]
		if self.mode == self.FAVORITELIST and self.getSelectedItem() is not None:
			options.extend(((_("rename current selected favorite"), self.renameFavorite),))
			options.extend(((_("remove current selected favorite"), self.removeFavorite),))
		elif self.mode == self.GENRELIST and self.getSelectedItem() is not None:
			options.extend(((_("Add current selected genre to favorite"), self.addGenreToFavorite),))
		elif self.mode == self.STATIONLIST and self.getSelectedItem() is not None:
			options.extend(((_("Add current selected station to favorite"), self.addStationToFavorite),))
		if len(self.currentStreamingURL) != 0:
			options.extend(((_("Add current playing stream to favorite"), self.addCurrentStreamToFavorite),))
		options.extend(((_("Hide"), self.hideWindow),))
		if self.pipZapAvailable is not None and SystemInfo.get("NumVideoDecoders", 1) > 1:
			options.extend(((_("Menu PiP"), self.activatePiP),))
		self.session.openWithCallback(self.menuCallback, ChoiceBox, list=options)

	def menuCallback(self, ret):
		ret and ret[1]()

	def hideWindow(self):
		self.visible = False
		self.hide()

	def showWindow(self):
		self.visible = True
		self.show()

	def addGenreToFavorite(self):
		sel = self.getSelectedItem()
		if sel is not None:
			self.addFavorite(name=sel.name, text=sel.name, favoritetype="genre")

	def addStationToFavorite(self):
		sel = self.getSelectedItem()
		if sel is not None:
			self.addFavorite(name=sel.name, text=self.SCY + f"/sbin/tunein-station.pls?id={sel.id}", favoritetype="pls", audio=sel.mt, bitrate=sel.br)

	def addCurrentStreamToFavorite(self):
		self.addFavorite(name=self.currentStreamingStation, text=self.currentStreamingURL, favoritetype="url")

	def addFavorite(self, name="", text="", favoritetype="", audio="", bitrate=""):
		self.favoriteConfig.entriescount.value = self.favoriteConfig.entriescount.value + 1
		self.favoriteConfig.entriescount.save()
		newFavorite = self.initFavouriteEntryConfig()
		newFavorite.name.value = name
		newFavorite.text.value = text
		newFavorite.type.value = favoritetype
		newFavorite.audio.value = audio
		newFavorite.bitrate.value = bitrate
		newFavorite.save()
		self.favoriteConfig.saveToFile(self.FAVORITE_FILE)

	def renameFavorite(self):
		sel = self.getSelectedItem()
		if sel is not None:
			self.session.openWithCallback(self.renameFavoriteFinished, VirtualKeyBoard, title=_("Enter new name for favorite item"), text=sel.config_item.name.value)

	def renameFavoriteFinished(self, text=None):
		if text:
			sel = self.getSelectedItem()
			sel.config_item.name.value = text
			sel.config_item.save()
			self.favoriteConfig.saveToFile(self.FAVORITE_FILE)
			self.favorite_list_idx = 0
			self.getFavoriteList()

	def removeFavorite(self):
		sel = self.getSelectedItem()
		if sel is not None:
			self.favoriteConfig.entriescount.value = self.favoriteConfig.entriescount.value - 1
			self.favoriteConfig.entriescount.save()
			self.favoriteConfig.Entries.remove(sel.config_item)
			self.favoriteConfig.Entries.save()
			self.favoriteConfig.saveToFile(self.FAVORITE_FILE)
			self.favorite_list_idx = 0
			self.getFavoriteList()

	def search(self):
		self.session.openWithCallback(self.searchSHOUTcast, VirtualKeyBoard, title=_("Enter text to search for"))

	def searchSHOUTcast(self, searchstring=None):
		if searchstring:
			self.stopReloadStationListTimer()
			self.stationListHeader = _("search-criteria %s") % searchstring
			self.headerTextString = _("SHOUTcast station list for %s") % self.stationListHeader
			self["headertext"].setText("")
			self["statustext"].setText(_("Searching SHOUTcast for %s...") % searchstring)
			self["list"].hide()
			if len(devid) > 8:
				self.stationListURL = self.SC + f"/station/advancedsearch&f=xml&k={devid}&search={searchstring}"
			else:
				self.stationListURL = ""
				# self.stationListURL = f"http://207.200.98.1/sbin/newxml.phtml?search={searchstring}"  # what's that? what for?
			self.mode = self.SEARCHLIST
			self.searchSHOUTcastString = searchstring
			self.station_list_idx = 0
			if self.stationListURL:
				send_url_command(self.stationListURL, None, 10).addCallback(self.callbackStationList).addErrback(self.callbackStationListError)

	def config(self):
		self.stopReloadStationListTimer()
		self.session.openWithCallback(self.setupFinished, SHOUTcastSetup)

	def setupFinished(self, result):
		if result:
			if config.plugins.shoutcast.showcover.value:
				self["cover"].doShow()
			else:
				self["cover"].doHide()
			if self.mode == self.STATIONLIST:
				self.reloadStationListTimerVar = int(config.plugins.shoutcast.reloadstationlist.value)
				self.station_list_idx = 0
				self.callbackStationList(self.stationListXML)

	def callbackStationListError(self, error=None):
		if error is not None:
			try:
				self["list"].hide()
				self["statustext"].setText(_("%s\nPress OK to try again...") % str(error.getErrorMessage()))
			except Exception:
				pass

	def Error(self, error=None):
		if error is not None:
			print(f"[SHOUTcast] Error: {error}\n")
			try:
				self["list"].hide()
				self["statustext"].setText(str(error.getErrorMessage()))
			except Exception:
				pass
		if self.nextGoogle:
			self.currentGoogle = self.nextGoogle
			self.nextGoogle = None
			send_url_command(self.currentGoogle, None, 10).addCallback(self.GoogleImageCallback).addErrback(self.Error)
		else:
			self.currentGoogle = None

	def __onClose(self):
		global coverfiles
		for f in coverfiles:
			try:
				unlink(f)
			except OSError:
				pass
		self.stopReloadStationListTimer()
		self.session.nav.playService(self.CurrentService)
		self.session.nav.event.remove(self.__event)
		self.currPlay = None
		containerStreamripper.dataAvail.remove(self.streamripperDataAvail)
		containerStreamripper.appClosed.remove(self.streamripperClosed)

	def GoogleImageCallback(self, result):
		global coverfiles
		bad_link = ['http://cdn.discogs.com', 'http://www.jaren80muziek.nl', 'http://www.inthestudio.net',
		'https://deepmp3.ru', 'http://beyondbreed.com', 'https://i1.sndcdn.com', 'http://www.lyrics007.com', 'https://lametralleta.es',
		'http://www.caramail.tv', 'http://cloud.freehandmusic.netdna-cdn.com', 'http://rockyourlyrics.com', 'http://www.franceinter.fr',
		'http://audio-max.home.pl', 'https://www.mystic.pl', 'http://radiobox2.omroep.nl', 'http://s0.hulkshare.com', 'http://static2.ising.pl',
		'http://www.disco-polo.info', 'http://merlin.pl', 'http://www.muzikbuldum.com', 'http://img2.zcdn.com.au', 'http://www.duoviva.com',
		'http://thumbnail.mixcloud.com', 'http://www.modern-talking.net', 'http://galleryplus.ebayimg.com', 'http://www.radiotrip.it',
		'https://dlmetal.org', 'http://i.iplsc.com', 'http://www.copertinedvd.org', 'http://flacmusic.org', 'https://imgcdn.ok.de',
		'http://www.mediaboom.org', 'http://democracy.allerdale.gov.uk', 'http://lahoradelrelax.com', 'http://www.isvent.com',
		'http://www.wallpaperfo.com', 'http://www.analyticdatasolutions.net', 'http://caratulascd.com', 'http://img.youtube.com',
		'http://satpic.ru', 'http://imagizer.imageshack.us']
		nr = 0
		url = 'http://memytutaj.pl/uploads/2015/07/27/55b66ab973ad1.jpg'
		if self.nextGoogle:
			self.currentGoogle = self.nextGoogle
			self.nextGoogle = None
			send_url_command(self.currentGoogle, None, 10).addCallback(self.GoogleImageCallback).addErrback(self.Error)
			return
		self.currentGoogle = None
		result = ensure_str(result)
		r = findall('murl&quot;:&quot;(http.*?)&quot', result, S | I)
		if r:
			url = r[nr]
			# FIXME loop
			_url = ensure_binary(url)
			if not _VALID_URI.match(_url):
				nr += 1
				url = r[nr]
			# FIXME nr max
			print(f"[SHOUTcast] fetch cover first try:{url}")
			for link in bad_link:
				if url.startswith(link):
					nr += 1
					url = r[nr]
					print(f"[SHOUTcast] fetch cover second try:{url}")
					for link in bad_link:
						if url.startswith(link):
							nr += 1
							url = r[nr]
							print(f"[SHOUTcast] fetch cover third try:{url}")
							for link in bad_link:
								if url.startswith(link):
									nr += 1
									url = r[nr]
									print(f"[SHOUTcast] fetch cover fourth try:{url}")
			if len(url) > 15:
				url = url.replace(" ", "%20")
				print(f"download url: {url} ")
				validurl = True
			else:
				validurl = False
				print("[SHOUTcast] invalid cover url or pictureformat!")
				if config.plugins.shoutcast.showcover.value:
					self["cover"].doHide()
			if validurl:
				self.currentcoverfile = (self.currentcoverfile + 1) % len(coverfiles)
				try:
					unlink(coverfiles[self.currentcoverfile - 1])
				except Exception:
					pass
				coverfile = coverfiles[self.currentcoverfile]
				print(f"[SHOUTcast] downloading cover from {url} to {coverfile} numer{str(nr)}")
				callInThread(self.threadDownloadPage, url, coverfile, (self.coverDownloadFinished, coverfile), self.coverDownloadFailed)

# FIXME [SHOUTcast] cover download failed: [Failure instance: Traceback: <class 'OpenSSL.SSL.Error'>: [('SSL routines', 'ssl3_read_bytes', 'sslv3 alert handshake failure')]

	def threadDownloadPage(self, link, file, success, fail=None):
		link = ensure_binary(link.encode('ascii', 'xmlcharrefreplace').decode().replace(' ', '%20').replace('\n', ''))
		try:
			response = get(link)
			response.raise_for_status()
			with open(file, "wb") as f:
				f.write(response.content)
			success(file)
		except exceptions.RequestException as error:
			if fail is not None:
				fail(error)

	def coverDownloadFailed(self, result):
		print("[SHOUTcast] cover download failed:", result)
		if config.plugins.shoutcast.showcover.value:
			self["statustext"].setText(_("Error downloading cover..."))
			self["cover"].doHide()

	def coverDownloadFinished(self, result, coverfile):
		if config.plugins.shoutcast.showcover.value:
			print("[SHOUTcast] cover download finished:", coverfile)
			self["statustext"].setText("")
			self["cover"].updateIcon(coverfile)
			self["cover"].doShow()

	# TODO : this needs to be refactored
	def __event(self, ev):
		if ev != 17 and ev != 18:
			print("[SHOUTcast] EVENT ==>", ev)
		if ev == 1:  # or ev == 4:
			print("[SHOUTcast] Tuned in, playing now!")
		elif ev == 3 or ev == 7:
			self["statustext"].setText(_("Stream stopped playing, playback of stream stopped!"))
			print("[SHOUTcast] Stream stopped playing, playback of stream stopped!")
			self.session.nav.stopService()
		elif ev == 271 or ev == 4:
			if not self.currPlay:
				return
			sTitle = self.currPlay.info().getInfoString(iServiceInformation.sTagTitle)
			if self.oldtitle != sTitle:
				self.oldtitle = sTitle
				sTitle = sTitle.replace("Title:", "")[:55]
				if config.plugins.shoutcast.showcover.value:
					searchpara = sTitle
					if sTitle:
						url = f"http://www.bing.com/images/search?q={quote(searchpara)}&FORM=HDRSC2"
					else:
						url = "http://www.bing.com/images/search?q={}&FORM=HDRSC2".format(quote('pamela anderson'))
					print(f"[SHOUTcast] coverurl = {url} ")
					if self.currentGoogle:
						self.nextGoogle = url
					else:
						self.currentGoogle = url
						send_url_command(url, None, 10).addCallback(self.GoogleImageCallback).addErrback(self.Error)
				if len(sTitle) == 0:
					sTitle = "n/a"
				title = _("Title: %s") % sTitle
				print(f"[SHOUTcast] Title: {title} ")
				self["titel"].setText(title)
				self.summaries.setText(title)
			else:
				print("[SHOUTcast] Ignoring useless updated info provided by streamengine!")

	def playServiceStream(self, url):
		self.currPlay = None
		self.session.nav.stopService()
		if config.plugins.shoutcast.showcover.value:
			self["cover"].doHide()
		sref = eServiceReference("4097:0:0:0:0:0:0:0:0:0:{}".format(url.replace(':', '%3a')))
		try:
			self.session.nav.playService(sref, adjust=False)
		except Exception:
			print(f"[SHOUTcast] Could not play {sref}")
		self.currPlay = self.session.nav.getCurrentService()
		self.currentStreamingURL = url
		self["titel"].setText(_("Title: n/a"))
		self["station"].setText(_("Station: %s") % self.currentStreamingStation)

	def createSummary(self):
		return SHOUTcastLCDScreen

	def initFavouriteEntryConfig(self):
		self.favoriteConfig.Entries.append(ConfigSubsection())
		i = len(self.favoriteConfig.Entries) - 1
		self.favoriteConfig.Entries[i].name = ConfigText(default="")
		self.favoriteConfig.Entries[i].text = ConfigText(default="")
		self.favoriteConfig.Entries[i].type = ConfigText(default="")
		self.favoriteConfig.Entries[i].audio = ConfigText(default="")
		self.favoriteConfig.Entries[i].bitrate = ConfigText(default="")
		return self.favoriteConfig.Entries[i]

	def initFavouriteConfig(self):
		count = self.favoriteConfig.entriescount.value
		if count != 0:
			i = 0
			while i < count:
				self.initFavouriteEntryConfig()
				i += 1

	def getSelectedItem(self):
		sel = None
		try:
			sel = self["list"].l.getCurrentSelection()[0]
		except Exception:
			return None
		return sel


class Cover(Pixmap):
	visible = 0

	def __init__(self):
		Pixmap.__init__(self)
		self.picload = ePicLoad()
		self.picload.PictureData.get().append(self.paintIconPixmapCB)
		self.decoding = None
		self.decodeNext = None

	def doShow(self):
		if not self.visible:
			self.visible = True
			print(f"[SHOUTcast] cover visible {self.visible} self.show")
			self.show()

	def doHide(self):
		if self.visible:
			self.visible = False
			print(f"[SHOUTcast] cover visible {self.visible} self.hide")
			self.hide()

	def onShow(self):
		Pixmap.onShow(self)
		coverwidth = self.instance.size().width()
		if int(config.plugins.shoutcast.cover_width.value) > coverwidth:
			config.plugins.shoutcast.cover_width.value = coverwidth
		coverheight = self.instance.size().height()
		if int(config.plugins.shoutcast.cover_height.value) > coverheight:
			config.plugins.shoutcast.cover_height.value = coverheight
		self.picload.setPara((coverwidth, coverheight, 1, 1, False, 1, "#00000000"))

	def paintIconPixmapCB(self, picInfo=None):
		ptr = self.picload.getData()
		if ptr is not None:
			self.instance.setPixmap(ptr.__deref__())
			if self.visible:
				self.doShow()
		if self.decodeNext is not None:
			self.decoding = self.decodeNext
			self.decodeNext = None
			if self.picload.startDecode(self.decoding) != 0:
				print("[Shoutcast] Failed to start decoding next image")
				self.decoding = None
		else:
			self.decoding = None

	def updateIcon(self, filename):
		if self.decoding is not None:
			self.decodeNext = filename
		else:
			if self.picload.startDecode(filename) == 0:
				self.decoding = filename
			else:
				print("[Shoutcast] Failed to start decoding image")
				self.decoding = None


class SHOUTcastList(GUIComponent):
	def buildEntry(self, item):
		width = self.l.getItemSize().width()
		res = [None]
		if self.mode == 0:  # GENRELIST
			print(f"[SHOUTcast] list name={item.name} haschilds={item.haschilds} opened={item.opened}\n")
			if item.parentid == "0":  # main genre
				if item.haschilds == "true":
					if item.opened == "true":
						iname = f"- {item.name}"
					else:
						iname = f"+ {item.name}"
				else:
					iname = item.name
			else:
				iname = f"     {item.name}"
			res.append((eListboxPythonMultiContent.TYPE_TEXT, 0, 0, width, self.pard, 0, RT_HALIGN_LEFT | RT_VALIGN_CENTER, iname))
		elif self.mode == 1:  # STATIONLIST
			res.append((eListboxPythonMultiContent.TYPE_TEXT, 0, 3, width, self.para, 1, RT_HALIGN_LEFT | RT_VALIGN_CENTER, item.name))
			res.append((eListboxPythonMultiContent.TYPE_TEXT, 0, self.parb, width, self.para, 1, RT_HALIGN_LEFT | RT_VALIGN_CENTER, item.ct))
			res.append((eListboxPythonMultiContent.TYPE_TEXT, 0, self.parc, width / 2, self.para, 1, RT_HALIGN_LEFT | RT_VALIGN_CENTER, _("Audio: %s") % item.mt))
			res.append((eListboxPythonMultiContent.TYPE_TEXT, width / 2, self.parc, width / 2, self.para, 1, RT_HALIGN_RIGHT | RT_VALIGN_CENTER, _("Bit rate: %s kbps") % item.br))
		elif self.mode == 2:  # FAVORITELIST
			res.append((eListboxPythonMultiContent.TYPE_TEXT, 0, 3, width, self.para, 1, RT_HALIGN_LEFT | RT_VALIGN_CENTER, item.config_item.name.value))
			res.append((eListboxPythonMultiContent.TYPE_TEXT, 0, self.parb, width, self.para, 1, RT_HALIGN_LEFT | RT_VALIGN_CENTER, f"{item.config_item.text.value} ({item.config_item.type.value})"))
			if len(item.config_item.audio.value) != 0:
				res.append((eListboxPythonMultiContent.TYPE_TEXT, 0, self.parc, width / 2, self.para, 1, RT_HALIGN_LEFT | RT_VALIGN_CENTER, _("Audio: %s") % item.config_item.audio.value))
			if len(item.config_item.bitrate.value) != 0:
				res.append((eListboxPythonMultiContent.TYPE_TEXT, width / 2, self.parc, width / 2, self.para, 1, RT_HALIGN_RIGHT | RT_VALIGN_CENTER, _("Bit rate: %s kbps") % item.config_item.bitrate.value))
		return res

	def __init__(self):
		GUIComponent.__init__(self)
		self.l = eListboxPythonMultiContent()
		self.fontsize0, self.fontsize1, self.cenrylist, self.favlist, self.para, self.parb, self.parc, self.pard = parameters.get("SHOUTcastListItem", (20, 18, 22, 69, 20, 23, 43, 22))
		self.onSelectionChanged = []
		self.mode = 0

	def setMode(self, mode):
		self.mode = mode
		if mode == 0:  # GENRELIST
			self.l.setItemHeight(self.cenrylist)
		elif mode == 1 or mode == 2:  # STATIONLIST OR FAVORITELIST
			self.l.setItemHeight(self.favlist)

	def connectSelChanged(self, fnc):
		if fnc not in self.onSelectionChanged:
			self.onSelectionChanged.append(fnc)

	def disconnectSelChanged(self, fnc):
		if fnc in self.onSelectionChanged:
			self.onSelectionChanged.remove(fnc)

	def selectionChanged(self):
		for x in self.onSelectionChanged:
			x()

	def getCurrent(self):
		cur = self.l.getCurrentSelection()
		return cur and cur[0]

	GUI_WIDGET = eListbox

	def postWidgetCreate(self, instance):
		instance.setContent(self.l)
		instance.setWrapAround(True)
		instance.selectionChanged.get().append(self.selectionChanged)

	def preWidgetRemove(self, instance):
		instance.setContent(None)
		instance.selectionChanged.get().remove(self.selectionChanged)

	def moveToIndex(self, index):
		self.instance.moveSelectionTo(index)

	def getCurrentIndex(self):
		return self.instance.getCurrentIndex()

	currentIndex = property(getCurrentIndex, moveToIndex)
	currentSelection = property(getCurrent)

	def setList(self, list):
		self.l.setList(list)

	def applySkin(self, desktop, parent):
		font = "Regular"
		for (attrib, value) in list(self.skinAttributes):
			if attrib == "font":
				font = value.split(";")[0]
				self.skinAttributes.remove((attrib, value))
				break
		self.l.setFont(0, gFont(font, self.fontsize0))
		self.l.setFont(1, gFont(font, self.fontsize1))
		self.l.setBuildFunc(self.buildEntry)
		self.l.setItemHeight(self.cenrylist)
		return GUIComponent.applySkin(self, desktop, parent)


class SHOUTcastLCDScreen(Screen):
	skin = """
	<screen position="0,0" size="132,64" title="SHOUTcast">
		<widget name="text1" position="4,0" size="132,14" font="Regular;12" halign="center" valign="center"/>
		<widget name="text2" position="4,14" size="132,49" font="Regular;10" halign="center" valign="center"/>
	</screen>"""

	def __init__(self, session, parent):
		Screen.__init__(self, session)
		self["text1"] = Label("SHOUTcast")
		self["text2"] = Label("")

	def setText(self, text):
		self["text2"].setText(text[0:39])


class SHOUTcastSetup(ConfigListScreen, Screen):

	skin = """
		<screen position="center,center" size="600,400" title="SHOUTcast Setup" >
			<ePixmap pixmap="skin_default/buttons/red.png" position="10,0" zPosition="0" size="140,40" transparent="1" alphatest="on" />
			<ePixmap pixmap="skin_default/buttons/green.png" position="155,0" zPosition="0" size="140,40" transparent="1" alphatest="on" />
			<ePixmap pixmap="skin_default/buttons/yellow.png" position="300,0" zPosition="0" size="140,40" transparent="1" alphatest="on" />
			<ePixmap pixmap="skin_default/buttons/blue.png" position="445,0" zPosition="0" size="140,40" transparent="1" alphatest="on" />
			<widget render="Label" source="key_red" position="10,0" size="140,40" zPosition="5" valign="center" halign="center" backgroundColor="red" font="Regular;21" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-1,-1" />
			<widget render="Label" source="key_green" position="150,0" size="140,40" zPosition="5" valign="center" halign="center" backgroundColor="red" font="Regular;21" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-1,-1" />
			<widget name="config" position="10,50" size="580,400" scrollbarMode="showOnDemand" />
		</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("SHOUTcast setup"))

		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("OK"))

		self.list = [
			getConfigListEntry(_("Show cover:"), config.plugins.shoutcast.showcover),
			getConfigListEntry(_("Coverwidth:"), config.plugins.shoutcast.cover_width),
			getConfigListEntry(_("Coverheight:"), config.plugins.shoutcast.cover_height),
			getConfigListEntry(_("Show in extension menu:"), config.plugins.shoutcast.showinextensions),
			getConfigListEntry(_("Streaming rate:"), config.plugins.shoutcast.streamingrate),
			getConfigListEntry(_("Reload station list:"), config.plugins.shoutcast.reloadstationlist),
			getConfigListEntry(_("Rip to single file, name is timestamped"), config.plugins.shoutcast.riptosinglefile),
			getConfigListEntry(_("Create a directory for each stream"), config.plugins.shoutcast.createdirforeachstream),
			getConfigListEntry(_("Add sequence number to output file"), config.plugins.shoutcast.addsequenceoutputfile),
				]
		self.dirname = getConfigListEntry(_("Recording location:"), config.plugins.shoutcast.dirname)
		self.list.append(self.dirname)

		ConfigListScreen.__init__(self, self.list, session)
		self["setupActions"] = ActionMap(["SetupActions", "ColorActions"],
		{
			"green": self.keySave,
			"cancel": self.keyClose,
			"ok": self.keySelect,
		}, -2)

	def keySelect(self):
		cur = self["config"].getCurrent()
		if cur == self.dirname:
			self.session.openWithCallback(self.pathSelected, SHOUTcastStreamripperRecordingPath, config.plugins.shoutcast.dirname.value)

	def pathSelected(self, res):
		if res is not None:
			config.plugins.shoutcast.dirname.value = res

	def keySave(self):
		if config.plugins.shoutcast.dirname.value == "":
			config.plugins.shoutcast.dirname.value = "/media/hdd/streamripper/"
		for x in self["config"].list:
			x[1].save()
		configfile.save()
		self.close(True)

	def keyClose(self):
		for x in self["config"].list:
			x[1].cancel()
		self.close(False)


class SHOUTcastStreamripperRecordingPath(Screen):
	skin = """<screen name="SHOUTcastStreamripperRecordingPath" position="center,center" size="560,320" title="Select record path for streamripper">
			<ePixmap pixmap="skin_default/buttons/red.png" position="0,0" zPosition="0" size="140,40" transparent="1" alphatest="on" />
			<ePixmap pixmap="skin_default/buttons/green.png" position="140,0" zPosition="0" size="140,40" transparent="1" alphatest="on" />
			<ePixmap pixmap="skin_default/buttons/yellow.png" position="280,0" zPosition="0" size="140,40" transparent="1" alphatest="on" />
			<ePixmap pixmap="skin_default/buttons/blue.png" position="420,0" zPosition="0" size="140,40" transparent="1" alphatest="on" />
			<widget name="target" position="0,60" size="540,22" valign="center" font="Regular;22" />
			<widget name="filelist" position="0,100" zPosition="1" size="560,220" scrollbarMode="showOnDemand"/>
			<widget render="Label" source="key_red" position="0,0" size="140,40" zPosition="5" valign="center" halign="center" backgroundColor="red" font="Regular;21" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-1,-1" />
			<widget render="Label" source="key_green" position="140,0" size="140,40" zPosition="5" valign="center" halign="center" backgroundColor="red" font="Regular;21" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-1,-1" />
		</screen>"""

	def __init__(self, session, initDir):
		Screen.__init__(self, session)
		self.setTitle(_("Select record path for streamripper"))
		inhibitDirs = ["/bin", "/boot", "/dev", "/etc", "/lib", "/proc", "/sbin", "/sys", "/usr", "/var"]
		inhibitMounts = []
		self["filelist"] = FileList(initDir, showDirectories=True, showFiles=False, inhibitMounts=inhibitMounts, inhibitDirs=inhibitDirs)
		self["target"] = Label()
		self["actions"] = ActionMap(["WizardActions", "DirectionActions", "ColorActions", "EPGSelectActions"],
		{
			"back": self.cancel,
			"left": self.left,
			"right": self.right,
			"up": self.up,
			"down": self.down,
			"ok": self.ok,
			"green": self.green,
			"red": self.cancel

		}, -1)
		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("OK"))

	def cancel(self):
		self.close(None)

	def green(self):
		self.close(self["filelist"].getSelection()[0])

	def up(self):
		self["filelist"].up()
		self.updateTarget()

	def down(self):
		self["filelist"].down()
		self.updateTarget()

	def left(self):
		self["filelist"].pageUp()
		self.updateTarget()

	def right(self):
		self["filelist"].pageDown()
		self.updateTarget()

	def ok(self):
		if self["filelist"].canDescent():
			self["filelist"].descent()
			self.updateTarget()

	def updateTarget(self):
		currFolder = self["filelist"].getSelection()[0]
		if currFolder is not None:
			self["target"].setText(currFolder)
		else:
			self["target"].setText(_("Invalid Location"))
