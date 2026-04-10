from Components.Language import language
from Tools.Directories import resolveFilename, SCOPE_PLUGINS
from gettext import bindtextdomain, dgettext, gettext


def locale_init():
	bindtextdomain("SHOUTcast", resolveFilename(SCOPE_PLUGINS, "Extensions/SHOUTcast/locale"))


def _(txt):
	t = dgettext("SHOUTcast", txt)
	if t == txt:
		# print "[SHOUTcast] fallback to default translation for", txt
		t = gettext(txt)
	return t


locale_init()
language.addCallback(locale_init)

__version__ = "1.1"
