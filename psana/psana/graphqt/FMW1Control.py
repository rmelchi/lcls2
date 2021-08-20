
"""Class :py:class:`FMW1Control` is a File Manager QWidget with control fields
==============================================================================

Usage ::

    # Run test: python lcls2/psana/psana/graphqt/FMW1Control.py

    from psana.graphqt.FMW1Control import FMW1Control
    w = FMW1Control()

Created on 2021-07-27 by Mikhail Dubrovin
"""

from psana.graphqt.CMWControlBase import * # CMWControlBase, QApplication, ..., icon, style, cp, logging, os, sys

logger = logging.getLogger(__name__)

class FMW1Control(CMWControlBase):
    """QWidget for File Manager control fields"""

    instr_exp_is_changed = pyqtSignal('QString', 'QString')

    def __init__(self, **kwa):

        CMWControlBase.__init__(self, **kwa)
        cp.fmw1control = self

        #expname = kwa.get('expname', cp.exp_name.value())
        expname = kwa.get('expname', expname_def())

        self.wfnm.setVisible(False)
        self.wfnm.setEnabled(False)

        self.lab_exp     = QLabel('Exp:')
        self.but_exp     = QPushButton(expname)
        self.but_exp_col = QPushButton('Collapse')

        self.box = QHBoxLayout() #QGridLayout()
        self.box.addWidget(self.lab_exp)
        self.box.addWidget(self.but_exp)
        self.box.addWidget(self.but_exp_col)
        self.box.addStretch(1)
        self.box.addWidget(self.but_save)
        self.box.addWidget(self.but_view)
        self.box.addWidget(self.but_tabs)
        self.setLayout(self.box)
 
        self.but_exp.clicked.connect(self.on_but_exp)
        self.but_exp_col.clicked.connect(self.on_but_exp_col)
#        self.but_save.clicked.connect(self.on_but_save)
#        self.connect_instr_exp_is_changed(self.on_instr_exp_is_changed)

        self.set_tool_tips()
        self.set_style()

        if cp.fmw1main is not None:
            global full_path_for_item
            from psana.graphqt.FSTree import full_path_for_item
            cp.fmw1main.wfstree.connect_item_selected_to(self.on_item_selected)
            cp.fmw1main.wfstree.clicked[QModelIndex].connect(self.on_click)


    def set_tool_tips(self):
        CMWControlBase.set_tool_tips(self)
        self.but_exp.setToolTip('Select experiment')
        self.but_save.setToolTip('To save array in file\nclick on *.data file in the tree\nthen click on this Save button')
        self.but_exp_col.setToolTip('Collapse/expand directory/file tree')


    def set_style(self):
        CMWControlBase.set_style(self)
        self.lab_exp.setStyleSheet(style.styleLabel)
        self.lab_exp.setFixedWidth(25)
        self.but_exp_col.setIcon(icon.icon_folder_open)
        self.but_exp.setFixedWidth(80)
        self.but_exp_col.setFixedWidth(80)
        #self.but_buts.setStyleSheet(style.styleButton)
        #self.but_tabs.setVisible(True)
        self.layout().setContentsMargins(5,0,5,0)


    def on_but_exp(self):
        from psana.graphqt.PSPopupSelectExp import select_instrument_experiment
        from psana.graphqt.CMConfigParameters import dir_calib #cp, 

        dir_instr = cp.instr_dir.value()
        instr_name, exp_name = select_instrument_experiment(None, dir_instr, show_frame=True) # parent=self.but_exp
        logger.debug('selected experiment: %s' % exp_name)
        if instr_name and exp_name and exp_name!=cp.exp_name.value():
            self.but_exp.setText(exp_name)
            cp.instr_name.setValue(instr_name)
            cp.exp_name.setValue(exp_name)

            if cp.fmw1main is not None:
               cp.fmw1main.wfstree.update_tree_model(dir_calib(exp_name))


    def on_but_exp_col(self):
        logger.debug('on_but_exp_col')
        if cp.fmw1main is None: return
        wtree = cp.fmw1main.wfstree
        but = self.but_exp_col
        if but.text() == 'Expand':
            wtree.process_expand()
            self.but_exp_col.setIcon(icon.icon_folder_closed)
            but.setText('Collapse')
        else:
            wtree.process_collapse()
            self.but_exp_col.setIcon(icon.icon_folder_open)
            but.setText('Expand')


    def on_but_view(self):
        """Re-implementation of the CMWControlBase.on_but_view"""
        logger.info('on_but_view - set file name and switch to IV')
        fname = cp.last_selected_fname.value()
        if fname is None:
            logger.warning('data file is not selected, do not switch to IV')
            return
        if cp.cmwmaintabs is not None:
            cp.cmwmaintabs.view_data(fname=fname)
        else:
            logger.info('tab bar object is not defined - do not switch to IV')


    def on_but_save(self):
        """Re-implementation of the CMWControlBase.on_but_save"""
        logger.warning('on_but_save - show the list of selected files')
        if cp.fmw1main is None: return
        wtree = cp.fmw1main.wfstree

        names_selected = [full_path_for_item(i) for i in wtree.selected_items()]
        if len(names_selected)==0:
            logger.warning('nothing is selected - click on desired dataset(s) it the tree.')
            return

        logger.info('selected file names:\n  %s' % '\n  '.join(names_selected))

#        self.instr_exp_is_changed.emit(instr_name, exp_name)

#    def connect_instr_exp_is_changed(self, recip):
#        self.instr_exp_is_changed.connect(recip)

#    def disconnect_instr_exp_is_changed(self, recip):
#        self.instr_exp_is_changed.disconnect(recip)

#    def on_instr_exp_is_changed(self, instr, exp):
#        logger.debug('selected instrument: %s experiment: %s' % (instr, exp))


    def view_hide_tabs(self):
        CMWControlBase.view_hide_tabs(self)
        # set file manager tabs in/visible too
        wtabs = cp.fmwtabs
        if wtabs is None: return
        is_visible = wtabs.tab_bar_is_visible()
        wtabs.set_tabs_visible(not is_visible)


    def save_item_path(self, index):
        i = cp.fmw1main.wfstree.model.itemFromIndex(index)
        if i is None:
           logger.info('on_item_selected: item is None')
           cp.last_selected_fname.setValue(None)
           cp.last_selected_data = None
           return
        fname = full_path_for_item(i)
        if os.path.exists(fname) and (not os.path.isdir(fname)):
            logger.info('save_item_path save last_selected_fname: %s path: %s' % (str(i.text()), fname))
            cp.last_selected_fname.setValue(fname)
            cp.last_selected_data = None


    def on_item_selected(self, selected, deselected):
        self.save_item_path(selected)


    def on_click(self, index):
        self.save_item_path(index)


    def closeEvent(self, e):
        logger.debug('closeEvent')
        CMWControlBase.closeEvent(self, e)
        cp.fmw1control = None


if __name__ == "__main__":
    os.environ['LIBGL_ALWAYS_INDIRECT'] = '1' #export LIBGL_ALWAYS_INDIRECT=1
    logging.basicConfig(format='[%(levelname).1s] %(name)s L%(lineno)04d : %(message)s', level=logging.DEBUG)

    app = QApplication(sys.argv)
    w = FMW1Control()
    w.setGeometry(100, 50, 500, 40)
    w.setWindowTitle('FM Control Panel')
    w.show()
    app.exec_()
    del w
    del app

# EOF