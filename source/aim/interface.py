"""Public interface to Ash Impact Modelling (AIM)

This module publishes one function, run_scenario() which will execute Fall3d based
on volcanological parameters specified in a scenario script (e.g. merapi.py), a
topographic data file and a wind profile dataset. The format of these files is
described in (FIXME: Add reference to manual here!).

AIM works with scenario modules containing all required volcanological parameters.


The function run_scenario() can be used in several ways:

------------------------
As a stand alone script:
------------------------

Create a new script run_scenario.py with the following contents:

import sys
from aim import run_scenario
run_scenario(sys.argv[1])


Models are run py executing run_scenario.py with the
scenario module as a command line argument, e.g.
python run_scenario.py merapi.py



---------------------------
Within the scenario script:
---------------------------

There are two options:

1) Run single scenario

Add the following code at the very end of the scenario module:

# Run model using specified parameters
if __name__ == '__main__':
    from aim import run_scenario
    run_scenario(__file__)

2) Run scenario based on dictionary of parameters
if __name__ == '__main__':
    from aim import run_scenario, get_scenario_parameters

    # Get parameters specified in scenario_file
    params = get_scenario_parameters(__file__)

    # Run scenario
    run_scenario(params)

In the latter case, it is then possible to run multiple scenarios with one or more parameters changing. E.g.

for x in [1,11,3,7]:
    params['x'] = x
    run_scenario(params)

Models are run py executing the scenario modules directly, e.g.
python merapi.py



The optional parameter, dircomment, provides a mechanism for tagging
the output directory with an arbitrary comment in addition to username and
date. This can for example be used to highlight a parameter that is looped,
e.g.

for x in [1,11,3,7]:
    params['x'] = x
    run_scenario(params, dircomment='x=%d' % x)

if dircomment is omitted, it will look for a
variable 'eruption_comment' and use that.
"""

import os, sys, time, string
import numpy

from config import tephra_output_dir
from utilities import get_scenario_parameters, header, run, makedir, get_eruptiontime_from_windfield, get_layers_from_windfield, get_fall3d_home, get_timestamp
from utilities import list_to_string, nc2asc
from utilities import generate_contours as _generate_contours
from utilities import build_output_dir
from wrapper import AIM
from coordinate_transforms import UTMtoLL, redfearn
from logmodule import start_logging

DEFAULT_SCENARIO_NAME = 'no_name'

def run_scenario(scenario,
                 dircomment=None,
                 store_locally=False,
                 timestamp_output=True,
                 verbose=True):
    """Run volcanic ash impact scenario

    The argument scenario can be either
    * A Python script
    or
    * A Dictionary

    In any case scenario must specify all required
    volcanological parameters as stated in the file required_parameters.txt.

    If any parameters are missing or if additional parameters are
    specified an exception will be raised.

    Optional parameters:
      dircomment: will be added to output dir for easy identification.
      store_locally: if True, don't use TEPHRAHOME for outputs
      timestamp_output: If True, add timestamp to output dir
                        If False overwrite previous output with same name

    """

    if isinstance(scenario, dict):
        # Establish scenario name is it is given as a dictionary
        if 'scenario_name' in scenario:
            scenario_name = scenario['scenario_name']
        else:
            # Default name
            scenario_name = scenario['scenario_name'] = DEFAULT_SCENARIO_NAME
    else:
        # Establish name of scenario in case it is a file
        try:
            x = os.path.split(scenario)[-1]
            scenario_name = os.path.splitext(x)[0]
        except:
            # Default name
            scenario_name = scenario['scenario_name'] = DEFAULT_SCENARIO_NAME


    # Get parameters from scenario
    params = get_scenario_parameters(scenario)

    # Create output area for single scenario
    if dircomment is None:
        dircomment = params['eruption_comment']

    # Establish whether there is multiple wind profiles
    wind_profile = params['wind_profile']
    if os.path.isdir(wind_profile):
        # Wind profile is a directory - transfer control to multiple windfield code

        # Create output area for multiple scenarios
        multiple_output_dir = build_output_dir(tephra_output_dir=tephra_output_dir,
                                               type_name='hazard_mapping',
                                               scenario_name=scenario_name,
                                               dircomment=dircomment,
                                               store_locally=store_locally,
                                               timestamp_output=timestamp_output)

        # Run scenario for each wind field
        run_multiple_windfields(scenario,
                                windfield_directory=wind_profile,
                                hazard_output_folder=multiple_output_dir)

        return None

    else:

        output_dir = build_output_dir(tephra_output_dir=tephra_output_dir,
                                      type_name='scenarios',
                                      scenario_name=scenario_name,
                                      dircomment=dircomment,
                                      store_locally=store_locally,
                                      timestamp_output=timestamp_output)

        logdir = os.path.join(output_dir, 'logs')
        makedir(logdir)
        AIM_logfile = os.path.join(logdir, 'AIM_%s.log' % scenario_name)
        start_logging(filename=AIM_logfile, echo=True, verbose=verbose)

        aim = _run_scenario(scenario,
                            dircomment=dircomment,
                            timestamp_output=timestamp_output,
                            store_locally=store_locally,
                            output_dir=output_dir,
                            verbose=verbose)

        # Return aim object in case further processing is needed
        return aim



def _run_scenario(scenario, dircomment=None,
                  store_locally=False,
                  timestamp_output=True,
                  output_dir=None,
                  verbose=True):
    """Run volcanic ash impact scenario

    The argument scenario can be either
    * A Python script
    or
    * A Dictionary

    In any case scenario must specify all required
    volcanological parameters as stated in the file required_parameters.txt.

    If any parameters are missing or if additional parameters are
    specified an exception will be raised.

    Optional parameters:
      dircomment: will be added to output dir for easy identification.
      store_locally: if True, don't use TEPHRAHOME for outputs
      timestamp_output: If True, add timestamp to output dir
                        If False overwrite previous output with same name



    """

    t_start = time.time()

    params = get_scenario_parameters(scenario)

    if dircomment is None:
        dircomment = params['eruption_comment']

    # Determine if any of the parameters provide are a tuple
    # in which case each combination is run separately
    for name in params:
        p = params[name]
        if type(p) is tuple:
            # Unpack tuple and run scenario for each parameter value
            # This recursion will continue until no parameters
            # have tuples as values
            params_unpacked = params.copy()
            for value in p:
                params_unpacked[name] = value
                aim = run_scenario(params_unpacked, dircomment=dircomment + '_%s_%s' % (name, value),
                                   store_locally=store_locally,
                                   timestamp_output=timestamp_output,
                                   verbose=verbose)

            return

    # Instantiate model object
    aim = AIM(params,
              dircomment=dircomment,
              store_locally=store_locally,
              timestamp_output=timestamp_output,
              output_dir=output_dir,
              verbose=verbose)

    if not aim.postprocessing:
        # Store scenario script, input data files and
        # actual parameters to provide a complete audit trail
        aim.store_inputdata(verbose=verbose)

        # Generate input file for Fall3d-6
        aim.write_input_file(verbose=verbose)

        # Generate input data files in Fall3D format
        aim.generate_topography(verbose=verbose)

        # Run scripts for Fall3d
        aim.set_granum(verbose=verbose)
        aim.set_database(verbose=verbose)
        aim.set_source(verbose=verbose)
        aim.run_fall3d(verbose=verbose)

    # Fall3d postprocessing nc2grd
    #aim.nc2grd()

    # AIM post processing
    aim.convert_ncgrids_to_asciigrids(verbose=verbose)
    #aim.convert_surfergrids_to_asciigrids()
    aim.generate_contours(verbose=verbose)

    aim.organise_output()

    # Done
    if verbose:
        header('Simulation finished in %.2f seconds, output data are in %s'
                   % (time.time() - t_start,
                      aim.output_dir))

        # FIXME (Ole): Commented out due to parallelisation
        #try:
        #    target = os.readlink(aim.symlink)
        #except:
        #    header('WARNING: Shortcut %s does not appear to be working. Use real directory instead.' % aim.symlink)
        #    #print 'Error message was', e
        #else:
        #
        #    if target == aim.output_dir:
        #        header('Shortcut to output data is: %s -> %s' % (aim.symlink, target))
        #    else:
        #        header('WARNING: Shortcut %s has been changed by more recent run to: %s' % (aim.symlink, target))
        #
        print

    # Return object in case user wants access to it
    # (e.g. for further postprocessing)
    return aim



def run_nc2prof(windfield_directory, verbose=True):
    """Run nc2prof - extract wind profiles from NCEP data

    Requires
        - input file
        - NCEP wind files
           TMP.nc
           HGT.nc
           UGRD.nc
           VGRD.nc
    """

    # FIXME: Perhaps include into AIM class (somehow)

    Fall3d_dir = get_fall3d_home()
    utilities_dir = os.path.join(Fall3d_dir, 'Utilities')
    executable = os.path.join(utilities_dir, 'nc2prof', 'nc2prof.exe')

    if verbose:
        header('Running nc2prof in %s' % windfield_directory)


    cmd = 'cd %s; %s ' % (windfield_directory, executable)

    logfile = 'run_nc2prof.log'
    run(cmd, verbose=verbose, stdout=logfile, stderr='/dev/null')


def run_hazardmap(model_output_directory, verbose=True):
    """Run HazardMapping.exe

    Requires
        - input file
        - Directory with FALL3D model outputs
    """

    # FIXME: Perhaps include into AIM class (somehow)

    Fall3d_dir = get_fall3d_home()
    utilities_dir = os.path.join(Fall3d_dir, 'Utilities')
    executable = os.path.join(utilities_dir, 'HazardMaps', 'HazardMapping.exe')

    if verbose:
        header('Running hazard mapping in %s' % model_output_directory)

    cmd = 'cd %s; %s ' % (model_output_directory, executable)

    logfile = 'run_hazardmapping.log'
    run(cmd, verbose=verbose, stdout=logfile, stderr='/dev/null')


def set_vent_location_in_windfield(filename, vent_location_easting, vent_location_northing, verbose=False):
    """Update vent location in UTM coordinates is set as specified in the arguments. UTM zone is implied by the context.
    """

    if verbose:
        print 'Patching', filename

    # Read file
    fid = open(filename)
    lines = fid.readlines()
    fid.close()

    # Replace vent location header (line 1) in file
    lines[0] = '%s %s\n' % (vent_location_easting, vent_location_northing)

    fid = open(filename, 'w')
    for line in lines:
        fid.write(line)
    fid.close()


def set_timeblocks_in_windfield(filename, verbose=False):
    """Update time blocks in seconds based on hour number in filename:


    Time blocks are updated based on the filename:

    For example

    ncep1_2009091306.profile

    represents the 6 hour block and corresponds to the block
    21600 43200

    """

    if verbose:
        print 'Patching', filename

    # Extract hour from filename
    basename, ext = os.path.splitext(filename)
    starthour = int(basename[-2:])
    endhour = starthour + 6

    startsec = starthour * 3600
    endsec = endhour * 3600
    if verbose:
        print '   Interval start: %i' % startsec
        print '   Interval end:   %i' % endsec

    # Read file
    fid = open(filename)
    lines = fid.readlines()
    fid.close()

    # Replace time block header (line 3) in file
    lines[2] = '%i %i\n' % (startsec, endsec)
    fid = open(filename, 'w')
    for line in lines:
        fid.write(line)
    fid.close()






def join_sorted_windprofiles(wind_data_files, outfilename):
    """Join multiple sorted wind data files into one.
    """

    outfile = open(outfilename, 'w')


    first_file = True
    for wind_data_file in wind_data_files:
        infile = open(wind_data_file)
        lines = infile.readlines()
        infile.close()

        if first_file:
            vent_loc = lines[0]
            date = lines[1]
            seconds_start, seconds_end = [int(x) for x in lines[2].split()]
            num_layers = int(lines[3])

            outfile.write(vent_loc)
            outfile.write(date)


        # Write time dependent information
        outfile.write('%i %i\n' % (seconds_start, seconds_end))
        outfile.write('%i\n' % num_layers)

        assert len(lines[4:]) == num_layers
        for line in lines[4:]:
            outfile.write(line)

        # Increment second blocks - this assumes 6 hour intervals!
        seconds_start = seconds_end
        seconds_end = seconds_start + 6*3600

        first_file = False

    outfile.close()


def join_wind_profiles(windfield_directory):
    """Join wind profiles generated by: generate_wind_profiles_from_ncep

    The parameter update_timeblocks *must* have been set to True in the generation
    """

    wind_data_files = {}
    seconds = []
    for x in os.listdir(windfield_directory):
        if x.endswith('profile'):
            basename, _ = os.path.splitext(x)

            hour = basename[-2:]
            date = basename[-4:-2]
            month = basename[-6:-4]

            timestring = '%s-%s-%sT%s%s%s' % ('2010', month, date, hour, '00', '00')
            time_tup = time.strptime(timestring, '%Y-%m-%dT%H%M%S')
            s = int(time.mktime(time_tup))

            seconds.append(s)
            wind_data_files[s] = x


    seconds.sort()
    wind_data_files = [wind_data_files[s] for s in seconds]

    wind_data_files = [os.path.join(windfield_directory, w) for w in wind_data_files]

    outfilename = windfield_directory
    base, _ = os.path.splitext(wind_data_files[0])
    outfilename += '_' + base[-6:] + '-'
    base, _ = os.path.splitext(wind_data_files[-1])
    outfilename += base[-6:] + '.profile'

    print 'Joining wind profiles into filename: %s' % outfilename

    join_sorted_windprofiles(wind_data_files, outfilename)




def generate_wind_profiles_from_ncep(scenario, update_timeblocks=False, verbose=True):
    """Generate wind profiles from NCEP data.

    The results are stored in a temporary directory specified in the variable windfield_directory
    Any previous data in that will be destroyed.
    """

    # Get params from model script
    params = get_scenario_parameters(scenario)

    windfield_directory = params['windfield_directory']


    # Convert UTM to latitude and longitude
    if params['vent_hemisphere'].upper() == 'S':
        is_southern_hemisphere = True
    elif params['vent_hemisphere'].upper() == 'N':
        is_southern_hemisphere = False
    else:
        msg = 'Parameter vent_hemisphere must be either N or S. I got %s' % params['vent_hemisphere']
        raise Exception(msg)


    lat, lon = UTMtoLL(params['vent_northing'],
                       params['vent_easting'],
                       params['vent_zone'],
                       is_southern_hemisphere)

    #print 'Lat, Lon', lat, lon
    #_, vent_location_easting, vent_location_northing = redfearn(lat, lon)
    #print vent_location_easting, params['vent_easting']
    #print vent_location_northing, params['vent_northing']



    # Clean up
    s = '/bin/rm -rf %s' % windfield_directory
    run(s)
    makedir(windfield_directory)

    # Link NCEP files to their original location
    NCEP_dir = params['NCEP_dir']

    for var in ['TMP', 'HGT', 'VGRD', 'UGRD']:
        s = 'cd %s; ln -s %s/%s.nc' % (windfield_directory, NCEP_dir, var)
        run(s, verbose=False)

    # Generate input file
    fid = open('%s/nc2prof.inp' % windfield_directory, 'w')
    fid.write('COORDINATES\n')
    fid.write('  LON_VENT = %f\n' % lon)
    fid.write('  LAT_VENT = %f\n' % lat)
    fid.write('EXTRACT_FROM\n')
    fid.write('  YEAR = %i\n' % params['start_year'])
    fid.write('  MONTH = %i\n' % params['start_month'])
    fid.write('  DAY = %i\n' % params['start_day'])
    fid.write('  HOUR = %i\n' % params['start_hour'])
    fid.write('EXTRACT_TO\n')
    fid.write('  YEAR = %i\n' % params['end_year'])
    fid.write('  MONTH = %i\n' % params['end_month'])
    fid.write('  DAY = %i\n' % params['end_day'])
    fid.write('  HOUR = %i\n' % params['end_hour'])
    fid.close()

    # Run nc2prof to extract profiles
    print 'Generating windfields for geographic vent location (%f, %f)' % (lon, lat)
    run_nc2prof(windfield_directory, verbose=False)


    # Patch wind profiles to have the correct vent location in UTM coordinates
    #from coordinate_transforms import redfearn
    #_, vent_location_easting, vent_location_northing = redfearn(lat, lon)

    print 'Patching windfields with UTM vent location (%i, %i)' % (params['vent_easting'], params['vent_northing'])
    for x in os.listdir(windfield_directory):
        if x.endswith('profile'):
            set_vent_location_in_windfield(os.path.join(windfield_directory, x),
                                           params['vent_easting'],
                                           params['vent_northing'],
                                           verbose=False)
            if update_timeblocks:
                set_timeblocks_in_windfield(os.path.join(windfield_directory, x),
                                            verbose=False)



    print 'Wind fields generated in directory: %s' % windfield_directory






#-----------------------------------
# Parallel computing and hazard maps
#-----------------------------------

def run_multiple_windfields(scenario,
                            windfield_directory=None,
                            hazard_output_folder=None,
                            dircomment=None,
                            echo=False,
                            verbose=True):
    """Run volcanic ash impact model for multiple wind fields.

    The wind fields are assumed to be in subfolder specified by windfield_directory,
    have the extension *.profile and follow the format use with scenarios.

    This function makes use of Open MPI and Pypar to execute in parallel but can also run sequentially.
    """

    try:
        import pypar
    except:
        P = 1
        p = 0
        processor_name = os.uname()[1]

        print 'Pypar could not be imported. Running sequentially on node %s' % processor_name,
    else:
        time.sleep(1)
        P = pypar.size()
        p = pypar.rank()
        processor_name = pypar.get_processor_name()

        print 'Processor %d initialised on node %s' % (p, processor_name)

        pypar.barrier()


    if p == 0:

        # Put logs along with the results
        logdir = os.path.join(hazard_output_folder, 'logs')
        makedir(logdir)

        header('Hazard modelling using multiple wind fields')
        print '*  Wind profiles obtained from: %s' % windfield_directory
        print '*  Scenario results stored in:  %s' %  hazard_output_folder
        print '*  Log files:'

        t_start = time.time()

        # Communicate hazard output directory name to all nodes to ensure they have exactly the same time stamp.
        for i in range(P):
            pypar.send((hazard_output_folder), i)
    else:
        # Receive correctly timestamped output directory names
        hazard_output_folder = pypar.receive(0)
        logdir = os.path.join(hazard_output_folder, 'logs')


    try:
        name = os.path.splitext(scenario)[0]
    except:
        name = 'run'


    # Wait until log dir has been created
    pypar.barrier()

    params = get_scenario_parameters(scenario)

    # Start processes staggered to avoid race conditions for disk access (otherwise it is slow to get started)
    time.sleep(2*p)

    # Logging
    s = 'Proc %i' % p
    print '     %s -' % string.ljust(s, 8),
    AIM_logfile = os.path.join(logdir, 'P%i.log' % p)
    start_logging(filename=AIM_logfile, echo=False)

    # Get cracking
    basename, _ = os.path.splitext(scenario)
    count_local = 0
    count_all = 0
    for i, file in enumerate(os.listdir(windfield_directory)):

        count_all += 1

        # Distribute jobs cyclically to processors
        if i%P == p:

            if not file.endswith('.profile'):
                continue

            count_local += 1

            windfield = '%s/%s' % (windfield_directory, file)
            windname, _ = os.path.splitext(file)
            header('Computing event %i on processor %i using wind field: %s' % (i, p, windfield))



            if dircomment is None:
                dircomment = params['eruption_comment']

            # Override or create parameters derived from native Fall3d wind field
            params['wind_profile'] = windfield
            params['wind_altitudes'] = get_layers_from_windfield(windfield) # FIXME: Try to comment this out.
            params['Meteorological_model'] = 'profile'

            if hazard_output_folder is None:
                hazard_output_folder = basename + '_hazard_outputs'

            if p == 0:
                print 'Storing multiple outputs in directory: %s' % hazard_output_folder

            # Run scenario
            aim = _run_scenario(params,
                                timestamp_output=True,
                                dircomment=dircomment + '_run%i_proc%i' % (i, p))

            # Make sure folder is present and can be shared by group
            makedir(hazard_output_folder)
            s = 'chmod -R g+w %s' % hazard_output_folder
            run(s)

            # Copy result file to output folder
            result_file = aim.scenario_name + '.res.nc'
            newname = aim.scenario_name + '.%s.res.nc' % windname # Name after wind file
            s = 'cp %s/%s %s/%s' % (aim.output_dir, result_file, hazard_output_folder, newname)
            run(s)

            # Create projectionfile in hazard output
            if i == 0:
                s = 'cp %s %s/%s' % (aim.projection_file, hazard_output_folder, 'HazardMaps.res.prj')
                run(s)

            # Clean up outputs from this scenario
            print 'P%i: Cleaning up %s' % (p, aim.output_dir)
            s = '/bin/rm -rf %s' % aim.output_dir
            run(s)

    print 'Processor %i done %i windfields' % (p, count_local)
    print 'Outputs available in directory: %s' % hazard_output_folder

    pypar.barrier()
    if p == 0:
        print 'Parallel simulation finished %i windfields in %i seconds' % (count_all, time.time() - t_start)


    pypar.finalize()




def generate_hazardmap(scenario, verbose=True):
    """Generate hazard map from Fall3d NetCDF outputs
    """

    # Get params from model script
    params = get_scenario_parameters(scenario)

    model_output_directory = params['model_output_directory']

    # Clean up
    s = 'cd %s; /bin/rm -rf HazardMaps.res.nc' % model_output_directory
    run(s)


    # Convert UTM to latitude and longitude
    if params['vent_hemisphere'].upper() == 'S':
        is_southern_hemisphere = True
    elif params['vent_hemisphere'].upper() == 'N':
        is_southern_hemisphere = False
    else:
        msg = 'Parameter vent_hemisphere must be either N or S. I got %s' % params['vent_hemisphere']
        raise Exception(msg)


    lat, lon = UTMtoLL(params['vent_northing'],
                       params['vent_easting'],
                       params['vent_zone'],
                       is_southern_hemisphere)

    # Get all model output files
    files = []
    for file in os.listdir(model_output_directory):
        if file.endswith('.nc'):
            files.append(file)


    # Generate input file
    fid = open('%s/HazardMaps.inp' % model_output_directory, 'w')
    fid.write('COORDINATES\n')
    fid.write('  LON_VENT = %f\n' % lon)
    fid.write('  LAT_VENT = %f\n' % lat)
    fid.write('POSTPROCESS\n')
    fid.write('  ISOCHRONES = yes\n')
    fid.write('  LOAD = yes\n')
    fid.write('  FL050 = no\n')
    fid.write('  FL100 = no\n')
    fid.write('  FL150 = no\n')
    fid.write('  FL200 = no\n')
    fid.write('  FL250 = no\n')
    fid.write('  FL300 = no\n')
    fid.write('VALUES\n')
    fid.write('  LOAD_VALUES = %s\n' % list_to_string(params['load_values']))
    fid.write('  FL_VALUES = %s\n' % list_to_string(params['fl_values']))
    fid.write('FILES\n')
    for file in files:
        fid.write(' \'%s\'\n' % file)
    fid.write('END_FILES\n')

    fid.close()

    # Run hazard maps
    print 'Generating hazard map for geographic vent location (%f, %f)' % (lon, lat)
    run_hazardmap(model_output_directory, verbose=False)

    print 'Hazard map done in directory: %s' % model_output_directory

    contour_hazardmap(scenario, verbose=verbose)


def contour_hazardmap(scenario, verbose=True):
    """Contouring hazard map from Fall3d NetCDF outputs located in directory given by the variable
    model_output_directory specified in scenario.

    The name of the hazard map is assumed to be HazardMaps.res.nc as per Fall3d

    """


    filename = 'HazardMaps.res.nc' # Hardwired name as per Fall3d

    from Scientific.IO.NetCDF import NetCDFFile

    # Get params from model script
    params = get_scenario_parameters(scenario)

    model_output_directory = params['model_output_directory']
    absolutefilename = os.path.join(model_output_directory, filename)

    if verbose:
        print 'Contouring hazard map %s' % absolutefilename


    # Converting NetCDF to ASCII files


    # Get variables
    fid = NetCDFFile(absolutefilename)
    variables = fid.variables.keys()
    if verbose:
        print 'Contouring variables %s' % str(variables)

    for var in variables:

        # Ignore x, y and time variables.
        if var in ['x', 'y', 'time']:
            continue

        # Look for data
        if var.startswith('PLOAD'):
            contours = params['PLOAD_contours']
            units = params['PLOAD_units']
            attribute_name = var
        elif var.startswith('ISOCHRO'):
            contours = params['ISOCHRON_contours']
            units = params['ISOCHRON_units']
            attribute_name = var
        else:
            if verbose: print 'WARNING: Undefined variable %s' % var
            continue

        # Look for projection file
        basename, _ = os.path.splitext(absolutefilename)
        prjfilename = basename + '.prj'
        if not os.path.exists(prjfilename):
            msg = 'Projection file %s must be present for contouring to work.\n' % prjfilename
            msg += 'You can copy the projection file from one of the individual scenarios used to produce the hazard map'
            raise Exception(msg)

        fid = open(prjfilename)
        WKT_projection = fid.read()
        fid.close()


        ascii_filename=nc2asc(absolutefilename,
                              subdataset=attribute_name,
                              projection=WKT_projection)

        for filename in os.listdir(model_output_directory):

            if filename.endswith('%s.asc' % attribute_name.lower()):
                # Contour all generated ASCII files

                _generate_contours(filename, contours, units, attribute_name,
                                   output_dir=model_output_directory,
                                   WKT_projection=True,
                                   verbose=verbose)



    if verbose:
        print 'Contouring of hazard map done in directory: %s' % model_output_directory

