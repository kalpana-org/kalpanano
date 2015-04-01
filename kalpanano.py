from datetime import datetime
import itertools
from math import ceil
import os.path
import re

from PyQt4 import QtCore, QtGui

from libsyntyche.common import read_file, kill_theming, read_json, write_json
from libsyntyche.common import make_sure_config_exists
from pluginlib import GUIPlugin

class UserPlugin(GUIPlugin):
    def __init__(self, objects, get_path):
        super().__init__(objects, get_path)
        self.sidebar = Sidebar(objects['textarea'], get_path())
        objects['mainwindow'].inner_h_layout.addWidget(self.sidebar)
        self.configpath = objects['settingsmanager'].get_config_directory()
        self.textarea = objects['textarea']
        self.textarea.file_saved.connect(self.on_save)
        self.local_path = get_path()
        self.hotkeys = {'Ctrl+B': self.toggle_sidebar}
        self.commands = {'x': (self.nano_command, 'NaNoWriMo command (x? for help)')}
        # NaNo-shit
        self.offset = 0
        self.activated = False

    def read_config(self):
        self.configfile = os.path.join(self.configpath, 'kalpanano.conf')
        defaultconfigfile = os.path.join(self.local_path, 'defaultconfig.json')
        make_sure_config_exists(self.configfile, defaultconfigfile)
        self.settings = read_json(self.configfile)
        self.day = self.settings['day']


    def nano_command(self, arg):
        oldday = self.day
        if arg == '?':
            self.print_('xs to init nanomode, xd to show day, xd+ to increase day')
        elif arg == 'd':
            self.print_('Day is {}'.format(self.day))
        elif arg == 'd+':
            self.day += 1
            self.print_('Day changed to {}'.format(self.day))
        elif re.match(r'd\d\d?$', arg):
            day = int(arg[1:])
            if day not in range(1,31):
                self.error('Invalid day')
                return
            self.day = day
            self.print_('Day changed to {}'.format(self.day))
        elif arg == 's':
            if not self.activated:
                if self.settings['override title wordcount']:
                    self.reconnect_wordcount_titlebar()
                logfile_path = self.get_logfile_path()
                if os.path.exists(logfile_path):
                    log = read_json(logfile_path)
                    self.offset = log.get('offset', 0)
                self.print_('Nano mode initiated.')
                self.activated = True
            else:
                self.error('Nano mode already running!')
        # Update the config just in case
        if self.day != oldday:
            self.settings = read_json(self.configfile)
            self.settings['day'] = self.day
            write_json(self.configfile, self.settings)

    def reconnect_wordcount_titlebar(self):
        """
        Change the wordcount in the title
        so that it is the same as in the nano sidebar.
        """
        self.textarea.document().contentsChanged.disconnect(self.textarea.contents_changed)
        def update_wordcount_in_titlebar():
            self.textarea.wordcount_changed.emit(self.get_wordcount()[0])
        self.textarea.document().contentsChanged.connect(update_wordcount_in_titlebar)
        update_wordcount_in_titlebar()


    def on_save(self):
        if not self.activated:
            return
        logfile_path = self.get_logfile_path()
        if os.path.exists(logfile_path):
            log = read_json(logfile_path)
        else:
            log = {'days':[], 'chapters':[]}
        wc, chapters = self.get_wordcount()
        log['chapters'] = chapters
        try:
            lastwc = int(log['days'][-1].split(';')[2])
        except IndexError:
            lastwc = 0
        if wc == lastwc:
            return
        log['days'].append('{};{};{}'.format(datetime.now(), self.day, wc))
        write_json(logfile_path, log)


    def get_logfile_path(self):
        root, fname = os.path.split(self.textarea.file_path)
        return root + '/.' + fname + '.nanolog'


    def written_today(self, total_wordcount):
        logfile_path = self.get_logfile_path()
        offset = 0
        if os.path.exists(logfile_path):
            days = read_json(self.get_logfile_path())['days']
            for x in days[::-1]:
                date, day, wc = x.split(';')
                if int(day) < self.day:
                    offset = int(wc)
                    break
        return total_wordcount - offset


    def get_wordcount(self):
        def count_words(lines):
            return len(re.findall(r'\S+', '\n'.join(lines)))
        text = self.textarea.toPlainText()
        text = re.sub(self.settings['wordcount']['ignorestr'], '', text, flags=re.DOTALL)
        lines = text.splitlines()
        endpoint = self.settings['wordcount']['endpoint']
        if endpoint in lines:
            lines = lines[:lines.index(endpoint)]
        # Find all remotely possible chapter lines (linenumber, text)
        rough_list = list(filter(lambda t:t[1].startswith(self.settings['chapter']['trigger']),
                                 zip(itertools.count(0), lines)))
        chapterlines = [0]
        if rough_list:
            rx = re.compile(self.settings['chapter']['regex'])
            chapterlines.extend([n for n, line in rough_list
                                 if rx.match(line)])
        chapterlines.append(len(lines))
        chapter_wc = [count_words(lines[chapterlines[i]:chapterlines[i+1]])
                      for i in range(len(chapterlines)-1)]
        return sum(chapter_wc)-self.offset, chapter_wc


    def update_sidebar(self):
        data = {'day': self.day, 'chapters':'', 'prevyears':''}
        data['totalwords'], chapters = self.get_wordcount()
        if self.offset > 0:
            data['offset'] = "<br><em><b>Offset:</b> {}</em>".format(self.offset)
        else:
            data['offset'] = ''
        data['percent'] = int(data['totalwords']/self.settings['goal']['words']*100)
        data['writtentoday'] = self.written_today(data['totalwords'])
        day_goal = ceil(self.settings['goal']['words'] / self.settings['goal']['days'])
        data['origdaygoal'] = day_goal - data['writtentoday']
        data['curdaygoal'] = ceil(((self.settings['goal']['words'] - (data['totalwords'] - data['writtentoday'])) / (self.settings['goal']['days']-self.day+1)) - data['writtentoday'])
        data['lefttopar'] = ceil((self.settings['goal']['words'] / self.settings['goal']['days'])*self.day - data['totalwords'])
        data['todos'] = self.textarea.toPlainText().count('TODO')
        data['todocolor'] = ('', 'style="color: red"')[data['todos'] > 0]
        chstr = '<tr><td align="right">{}</td><td align="right">{}</td><td align="right">{}</td></tr>'
        def get_diff(chapter, length):
            if not self.settings['chapter']['length'] or chapter == 0:
                return ''
            else:
                return self.settings['chapter']['length']-length
        data['chapters'] = ''.join(\
                    [chstr.format(n, c, get_diff(n,c))
                     for n, c in enumerate(chapters)])
        self.sidebar.update_data(data)


    def toggle_sidebar(self):
        if not self.activated:
            self.error('NaNo mode not initiated!')
            return
        if self.sidebar.isVisible():
            self.sidebar.hide()
        else:
            self.sidebar.show()
            self.update_sidebar()



class Sidebar(QtGui.QTextEdit):
    def __init__(self, textarea, local_path):
        super().__init__()
        self.html = read_file(os.path.join(local_path, 'sidebar.html'))
        self.setStyleSheet("Sidebar {border: 0px; border-left: 2px solid #111}")
        self.setReadOnly(True)
        self.hide()

    def update_data(self, data):
        self.setHtml(self.html.format(**data))
        # Ugly pos crappy hack
        self.setFixedWidth(self.sizeHint().width()*0.81)
