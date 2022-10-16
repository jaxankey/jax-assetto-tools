#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import glob, codecs, os, sys, shutil, json, stat
from scipy.signal import savgol_filter
from numpy import interp, linspace, nan_to_num
from configparser import ConfigParser


# Change to the directory of this script depending on whether this is a "compiled" version or run as script
if os.path.split(sys.executable)[-1] == 'uploader.exe': os.chdir(os.path.dirname(sys.executable)) # For executable version
else:                                                   os.chdir(os.path.dirname(os.path.abspath(__file__)))
print('WORKING DIRECTORY:')
print(os.getcwd())

# Library for all the gui and plotting.
import spinmob
import spinmob.egg as egg

# Function for loading a json at the specified path
def load_json(path):
    """
    Load the supplied path with all the safety measures and encoding etc.
    """
    try:
        if os.path.exists(path):
            f = codecs.open(path, 'r', 'utf-8-sig', errors='replace')
            #f = open(path, 'r', encoding='utf8', errors='replace')
            j = json.load(f, strict=False)
            f.close()
            return j
    except Exception as e:
        print('ERROR: Could not load', path)
        print(e)

def rm_readonly(func, path, excinfo):
    os.chmod(path, stat.S_IWRITE)
    func(path)

def rmtree(top):
    """
    Implemented to take care of chmodding
    """
    shutil.rmtree(top, onerror=rm_readonly)

class Modder:
    """
    GUI class for searching and modding content.
    """

    def __init__(self, show=True, blocking=True):

        # When updating cars, we want to suppress some signals.
        self._updating_cars = False

        # Lookup table to convert from user-friendly settings to keys in ini files.
        self.ini = {
            'CAR.INI'           : {
                'Mass'          : 'BASIC/TOTALMASS',
            },
            'DRIVETRAIN.INI'    : {
                'Power'         : 'DIFFERENTIAL/POWER',
                'Coast'         : 'DIFFERENTIAL/COAST',
                'Preload'       : 'DIFFERENTIAL/PRELOAD',
            },
            'SUSPENSIONS.INI'   : {
                'Front Height'  : 'FRONT/ROD_LENGTH',
                'Front Travel'  : 'FRONT/PACKER_RANGE',
                'Rear Height'   : 'REAR/ROD_LENGTH',
                'Rear Travel'   : 'REAR/PACKER_RANGE',
            },
        }
        

        ######################
        # Build the GUI

        # Main window
        self.window = egg.gui.Window('Assetto Corsa Minimodder', size=(1200,700), autosettings_path='window')

        # Top grid controls
        self.grid_top = self.window.add(egg.gui.GridLayout(False), alignment=0)

        self.grid_top.add(egg.gui.Label('Local Assetto Path:'))
        self.text_local = self.grid_top.add(egg.gui.TextBox(
            'C:\\path\\to\\assettocorsa',
            tip='Local path to assettocorsa folder.', 
            autosettings_path='text_local'), alignment=0)
        self.button_browse_local = self.grid_top.add(egg.gui.Button('Browse',
            tip='Opens a dialog to let you find the local assettocorsa folder.',
            signal_clicked=self._button_browse_local_clicked))
        self.button_scan = self.grid_top.add(egg.gui.Button('Scan',
            tip='Scans this Assetto directory for content.',
            signal_clicked=self._button_scan_clicked))

        # Combo row
        self.window.new_autorow()
        self.grid_middle = self.window.add(egg.gui.GridLayout(False), alignment=1)
        self.combo_car = self.grid_middle.add(egg.gui.ComboBox([], 
            autosettings_path='combo_car',
            signal_changed=self._combo_car_changed,).set_width(180))
        self.combo_car.load_gui_settings(True)
        last_car_index = self.combo_car._lazy_load['self']
        self.button_load_car = self.grid_middle.add(egg.gui.Button(
            'Load Car Data', signal_clicked=self._button_load_car_clicked)).hide()

        self.button_open_car_folder = self.grid_middle.add(egg.gui.Button(
            'Open Car Folder', signal_clicked=self._button_open_car_folder_clicked))
        
        self.button_create_mod = self.grid_middle.add(egg.gui.Button(
            'Create Mod', signal_clicked=self._button_create_mod_clicked))
        
        # Settings and plot row
        self.window.new_autorow()
        self.grid_middle2 = self.window.add(egg.gui.GridLayout(False), alignment=0)
        self.tree = self.grid_middle2.add(egg.gui.TreeDictionary(
            autosettings_path='tree', new_parameter_signal_changed=self._tree_changed),
            row_span=2)
        self.tree.set_minimum_width(210)

        # Settings
        self.tree.add('Mod Tag', 'R')
        
        self.tree.add('POWER.LUT', False)
        self.tree.add('POWER.LUT/Restrictor', False)
        self.tree.add('POWER.LUT/Restrictor/Exponent', 0.3, step=0.05)
        self.tree.add('POWER.LUT/Restrictor/RPM Range', 1.0, step=0.05, limits=(0,None))
        self.tree.add('POWER.LUT/Smooth', False)
        self.tree.add('POWER.LUT/Smooth/Points', 100)
        self.tree.add('POWER.LUT/Smooth/Window', 5)
        self.tree.add('POWER.LUT/Smooth/Order', 3)
        
        for key in self.ini:
            self.tree.add(key, False)
            for k in self.ini[key]:
                self.tree.add(key+'/'+k, 0.0)
                self.tree.add(key+'/'+k+'/->', 0.0)
                
        self.tree.load_gui_settings()
        
        # Make the plotter
        self.plot = self.grid_middle2.add(egg.gui.DataboxPlot(autosettings_path='plot'), alignment=0)        
        
        # Log area
        self.window.new_autorow()
        #self.grid_bottom = self.window.add(egg.gui.GridLayout(False), alignment=0)  
        self.text_log = self.grid_middle2.add(egg.gui.TextLog(), 1,1, alignment=0)
        
        self.log('Welcome to my silly-ass minimodder!')
        
        # Scan for content
        self.button_scan.click()
        self.combo_car.set_index(last_car_index)
        
        # Show it.
        self.window.show(blocking)

    def _button_create_mod_clicked(self, *a):
        """
        Duplicates the currently selected car and creates a modded version.
        """
        
        # Get the mod name and new folder name
        car_name = self.combo_car.get_text()
        car = self.srac[car_name]
        car_path = os.path.realpath(os.path.join(self.text_local(), 'content', 'cars', car))
        mod_name = self.combo_car.get_text() + '-'+self.tree['Mod Tag']
        mod_car  = car+'_'+self.tree['Mod Tag'].lower().replace(' ', '_')
        mod_car_path = os.path.realpath(os.path.join(self.text_local(), 'content', 'cars', mod_car))
        
        # Create a warning dialog and quit if cancelled
        qmb = egg.pyqtgraph.QtGui.QMessageBox
        ret = qmb.question(self.window._window, '******* WARNING *******', 
          "This will create the mod '"+mod_name+"' and create / overwrite the folder "+mod_car_path, 
          qmb.Ok | qmb.Cancel, qmb.Cancel)
        if ret == qmb.Cancel: return

        self.log('Creating '+mod_name)
        
        # If the other directory is already there, kill it.
        if os.path.exists(mod_car_path): 
            self.log('  Deleting '+mod_car_path)
            rmtree(mod_car_path)
        
        # Copy the existing mod as is
        self.log('  Copying '+car+' -> '+mod_car)
        shutil.copytree(car_path, mod_car_path)
        
        # Now update power.lut
        if self.tree['POWER.LUT']:
            self.log('  Updating power.lut')
            d = self.plot
            mod_power_path = os.path.realpath(os.path.join(mod_car_path,'data','power.lut'))
            f = open(mod_power_path, 'w')
            for n in range(len(d[0])):
                if d[2][n]:
                    line = '%.1f|%.1f\n' % (d[0][n], d[2][n])
                    f.write(line)
            f.close()
        
        # Now update the ui.json
        self.log('  Updating ui_car.json')
        mod_ui = os.path.realpath(os.path.join(mod_car_path, 'ui', 'ui_car.json'))
        x = load_json(mod_ui)
        x['name'] = mod_name
        x['torqueCurve'] = []
        x['powerCurve']  = []
        hp = d[0]*d[2]*0.00014
        for n in range(len(d[0])):
            if d[2][n]:
                x['torqueCurve'].append(['%.1f'%d[0][n], '%.1f'%d[2][n]])
                x['powerCurve'] .append(['%.1f'%d[0][n], '%.1f'%hp[n]  ])
        x['specs']['bhp']      = '%.0f bhp' % max(hp) 
        x['specs']['torque']   = '%.0f Nm'  % max(d[2])
        x['specs']['weight']   = '%.0f kg'  % self.tree['CAR.INI/Mass/->']
        x['specs']['pwratio']  = '%.2f kg/bhp' % (self.tree['CAR.INI/Mass/->']/max(hp))
        x['specs']['topspeed'] = 'buh?'
        x['minimodder'] = self.tree.get_dictionary()[1]
        json.dump(x, open(mod_ui, 'w'), indent=2)

        ##################
        # INI FILES
        ##################
        for key in self.ini:
            self.log('  Updating '+key)
            
            # Read the existing ini file
            with open(os.path.join(mod_car_path,'data',key.lower())) as f: ls = f.readlines()
            
            # Loop over lines, keeping track of the section
            section = ''
            for n in range(len(ls)):
     
                # Check if this is a section header
                if ls[n][0] == '[': 
                    section = ls[n][1:].split(']')[0].strip()
                    #self.log('   ['+section+']')
                
                # Otherwise, do the key-value thing
                else:
                    b = ls[n].split('=')[0].strip()
                    ab = section+'/'+b
                    for k in self.ini[key]:
                        if ab == self.ini[key][k]: 
                            ls[n] = b+'='+str(self.tree[key+'/'+k+'/->'])
                            self.log('     '+b+'='+str(self.tree[key+'/'+k+'/->']))
        
        # Now delete the data.acd
        mod_data_acd = os.path.join(mod_car_path, 'data.acd')
        if os.path.exists(mod_data_acd):
            self.log('  Deleting mod data.acd (don\'t forget to pack!)')
            os.unlink(mod_data_acd)
        
        # Update sfx
        mod_guids = os.path.join(mod_car_path, 'sfx', 'GUIDs.txt')
        if os.path.exists(mod_guids):
            self.log('  Updating '+mod_guids)
            with open(mod_guids, 'r') as f: s = f.read()
            with open(mod_guids, 'w') as f: f.write(s.replace(car, mod_car))
        
        # Renaming bank
        self.log('Renaming '+car+'.bank -> '+mod_car+'.bank')
        os.rename(os.path.join(mod_car_path, 'sfx', car    +'.bank'),
                  os.path.join(mod_car_path, 'sfx', mod_car+'.bank'))
        
        # Remember our selection and scan
        self.button_scan.click()
        self.combo_car.set_index(self.combo_car.get_index(car_name))
        
        # Open the mod car path
        os.startfile(mod_car_path)
    
    def load_ini(self, *path_args):
        """
        Returns ConfigParser
        """
        c = ConfigParser()
        c.optionxform=str
        path = os.path.join(*path_args)
        self.log('  Loading '+path)
        c.read(path)
        return c
        
    def get_floats_from_ini(self, path, *keys):
        """
        Returns a dictionary of key:value pairs for the supplied keys.
        e.g. get_init_values('C:\...\thing.ini', 'INTERTIA', 'PANTS', 'SHOES')
        """
        
        r = dict()
        # Read in the ini
        with open(path) as f: lines = f.readlines()
        
        for line in lines:
            
            key = line.split('=')[0].strip()
            if key in keys:
                r[key] = line.split('=')[1].split(';')[0].strip()
        
        return r
        

    def mod_and_overwrite_ini(self, path, **kwargs):
        """
        Modifies the specified values
        
        e.g. mod_and_overwrite_ini('C:\...\my_car\data\car.ini', INERTIA=0.8)
        """
        self.log('  Modding '+path)

        # Read in the og
        with open(path) as f: lines = f.readlines()
                
        # Update lines
        for n in range(len(lines)):
            line = lines[n]
        
            # Get the key
            key = line.split('=')[0].strip()
            if key in kwargs: 
                lines[n] = key+'='+str(kwargs[key])+'\n'
                self.log('    '+line.split(';')[0].strip()+' -> '+lines[n].split('=')[1].strip())
                
        # Now overwrite
        with open(path, 'w') as f: f.write(''.join(lines))

    def _button_open_car_folder_clicked(self, *a):
        """
        Opens the car directory.
        """
        car  = self.srac[self.combo_car.get_text()]
        path = os.path.realpath(os.path.join(self.text_local(), 'content', 'cars', car))
        self.log('Opening', path)
        os.startfile(path)

    def _combo_car_changed(self, *a):
        """
        Someone changed the car combo.
        """
        if self._updating_cars: return
        self.log('New car selected.')
        self.load_car_data()

    def _button_load_car_clicked(self, *a):
        """
        Someone clicked the "Load Car Data" button.
        """
        self.load_car_data()
    
    def load_car_data(self):
        """
        Loads the car data.
        """
        
        # Get the path to the car
        car  = self.srac[self.combo_car.get_text()]
        data = os.path.realpath(os.path.join(self.text_local(), 'content', 'cars', car, 'data'))

        self.log('Loading '+self.combo_car.get_text()+' data:')
        if not os.path.exists(data):
            self.log('  ERROR: '+data+ ' does not exist. Make sure you have unpacked data.acd.')
            self.button_create_mod.disable()
            self.plot.clear()
            self.plot.plot()
            self.grid_middle2.disable()
            return
        
        self.log('  Found '+data)
        self.button_create_mod.enable()
        self.grid_middle2.enable()
        
        # power.lut path
        power_lut = os.path.join(data, 'power.lut')
        self.plot.load_file(power_lut, delimiter='|')
        self.data = spinmob.data.databox()
        self.data.copy_all_from(self.plot)
        self.update_curves()
        
        # Load other ini settings into the tree
        for key in self.ini:
            c = self.load_ini(data, key.lower())
            for k in self.ini[key]:
                a,b = self.ini[key][k].split('/')
                self.tree[key+'/'+k] = c[a][b]
                if self.tree[key+'/'+k+'/->'] == 0:
                    self.tree[key+'/'+k+'/->'] = c[a][b]
                
        

    def update_curves(self):
        """
        Calculates and updates the plot.
        """
        if not len(self.plot): return
        
        self.plot.copy_all_from(self.data)
        
        # Update the plot
        x = self.plot[0]
        y = self.plot[1]
        
        # If we're smoothing
        if self.tree['POWER.LUT/Smooth']:
            
            # Sav-Gol filter
            x2 = linspace(min(x),max(x),self.tree['POWER.LUT/Smooth/Points'])
            y2 = interp(x2, x, y)
            x = self.plot[0] = x2
            y = self.plot[1] = savgol_filter(y2, self.tree['POWER.LUT/Smooth/Window'], self.tree['POWER.LUT/Smooth/Order'])
    
        x0 = max(self.plot[0])*self.tree['POWER.LUT/Restrictor/RPM Range']
        p  = self.tree['POWER.LUT/Restrictor/Exponent']
        
        if self.tree['POWER.LUT/Restrictor']:
            self.plot['Modded'] = nan_to_num(y*((x0-x)/x0)**p, 0)
            self.plot['Scale']  = nan_to_num(((x0-x)/x0)**p, 0)
            
        else:
            self.plot['Modded'] = y
            self.plot['Scale'] = 0*x+1
        
        self.plot.plot()

    def _tree_changed(self, *a):
        """
        Setting in the tree changed.
        """
        self.update_curves()
        

    def _button_scan_clicked(self, *a):
        """
        Scans the content directory for things to mod.
        """
        self.update_cars()

    def _button_browse_local_clicked(self, e):
        """
        Pop up the directory selector.
        """
        path = egg.dialogs.select_directory(text='Select the Assetto Corsa directory, apex-nerd.', default_directory='assetto_local')
        if(path):
            self.text_local(path)
            self.button_scan.click()

    def log(self, *a):
        """
        Logs it.
        """
        a = list(a)
        for n in range(len(a)): a[n] = str(a[n])
        text = ' '.join(a)
        self.text_log.append_text(text)
        print('LOG:',text)
        self.window.process_events()

    def update_cars(self):
        """
        Searches through the current assetto directory for all cars, skins, etc.
        """
        self.log('Updating cars...')
        self._updating_cars = True
        
        # Dictionary to hold all the model names
        self.cars  = dict()
        self.srac  = dict() # Reverse-lookup
        self.skins = dict()

        # Get all the car paths
        for path in glob.glob(os.path.join(self.text_local(), 'content', 'cars', '*')):

            # Get the car's directory name
            dirname = os.path.split(path)[-1]

            # Make sure it exists.
            path_json = os.path.join(path, 'ui', 'ui_car.json')
            if not os.path.exists(path_json): continue

            # Get the fancy car name (the jsons are not always well formatted, so I have to manually search!)
            s = load_json(path_json)

            # Remember the fancy name
            name = s['name'] if 'name' in s else dirname
            self.cars[dirname] = name
            self.srac[name]    = dirname

            # Store the list of skins and the index
            self.skins[dirname] = os.listdir(os.path.join(path, 'skins'))

        # Sort the car directories and add them to the list.
        self.cars_keys = list(self.cars.keys())
        self.srac_keys = list(self.srac.keys())
        self.cars_keys.sort()
        self.srac_keys.sort()
        
        # Populate the combo
        self.combo_car.clear()
        for key in self.srac_keys: self.combo_car.add_item(key)
        
        self._updating_cars = False
        

    def update_tracks(self):
        """
        Searches through the assetto directory for all the track folders
        """
        print('update_tracks')
        # Clear existing
        self._refilling_tracks = True
        self.combo_tracks.clear()

        # Get all the paths
        #self.log('Updating tracks...')
        paths = glob.glob(os.path.join(self.text_local(), 'content', 'tracks', '*'))
        paths.sort()
        for path in paths: self.combo_tracks.add_item(os.path.split(path)[-1])
        self._refilling_tracks = False


# Start the show!
self = Modder()