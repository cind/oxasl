#!/usr/bin/env python
"""
BASIL - Bayesian model fitting for ASL

Copyright (c) 2008-2018 University of Oxford
"""

import sys

from fsl.wrappers import LOAD

from ._version import __version__, __timestamp__
from .image import AslImage, AslImageOptions
from .workspace import Workspace
from .options import AslOptionParser, OptionCategory, IgnorableOptionGroup, GenericOptions

def basil(wsp, output_wsp=None, prefit=True):
    """
    Run BASIL modelling on ASL data in a workspace

    :param wsp: Workspace object
    :param output_wsp: Optional Workspace object for storing output. If not specified
                       will use ``wsp`` 
    :param prefit: If True, run a pre-fitting step using the mean over repeats of the ASL data

    Required workspace attributes
    -----------------------------

     - ``asldata`` : AslImage object

    Optional workspace attributes
    -----------------------------

     - ``mask`` : Brain mask (fsl.Image)
     - ``wp`` : If True, use 'white paper' mode (Alsop et al) - modifies some defaults and infers tissue component only
     - ``infertiss`` : If True, infer tissue component (default: True)
     - ``inferbat`` : If True, infer bolus arrival time (default: False)
     - ``infertau`` : If True, infer bolus duration (default: False)
     - ``inferart`` : If True, infer arterial component (default: False)
     - ``infert1`` : If True, infer T1 (default: False)
     - ``inferpc`` : If True, infer PC (default: False)
     - ``spatial`` : If True, include final spatial VB step (default: False)
     - ``onestep`` : If True, do all inference in a single step (default: False)
     - ``t1im`` : T1 map as Image
     - ``pgm`` :  Grey matter partial volume map as Image
     - ``pwm`` : White matter partial volume map as Image
     - ``initmvn`` : MVN structure to use as initialization as Image   
     - ``t1``: Assumed/initial estimate for tissue T1 (default: 1.65 in white paper mode, 1.3 otherwise)
     - ``t1b``: Assumed/initial estimate for blood T1 (default: 1.65)
     - ``bat``: Assumed/initial estimate for bolus arrival time (s) (default 0 in white paper mode, 1.3 for CASL, 0.7 otherwise)
     - ``tau`` : Assumed/initial estimate for bolus duration  (default: 1.8) 
     - ``basil_options`` : Optional dictionary of additional options for underlying model
    """
    wsp.log.write("\nRunning BASIL Bayesian modelling on ASL data\n")
    if output_wsp is None:
        output_wsp = wsp

    # Single or Multi TI setup
    if wsp.asldata.ntis == 1:
        # Single TI data - don't try to infer arterial component of bolus duration, we don't have enough info
        wsp.log.write(" - Operating in Single TI mode - no arterial component, fixed bolus duration\n")
        wsp.inferart = False
        wsp.infertau = False
        
    if wsp.wp:
        # White paper mode - this overrides defaults, but can be overwritten by command line 
        # specification of individual parameters
        wsp.log.write(" - Analysis in white paper mode: T1 default=1.65, BAT default=0, voxelwise calibration\n")
        t1_default = 1.65
        bat_default = 0.0
        #wsp.calib_method = "voxel"
    else:
        t1_default = 1.3
        if wsp.casl:
            bat_default = 1.3
        else:
            bat_default = 0.7

    if wsp.t1 is None: wsp.t1 = t1_default
    if wsp.t1b is None: wsp.t1b = 1.65
    if wsp.bat is None: wsp.bat = bat_default
    if wsp.tau is None: wsp.tau = 1.8
    if wsp.infertiss is None: wsp.infertiss = True
        
    # if we are doing CASL then fix the bolus duration, except where the user has 
    # explicitly told us otherwise
    if wsp.infertau is None: wsp.infertau = not wsp.casl

    # Pick up extra BASIL options
    extra_options = wsp.basil_options
    if extra_options is None:
        extra_options = {}

    if prefit and max(wsp.asldata.rpts) > 1:
        # Initial BASIL run on mean data
        wsp.log.write(" - Doing initial fit on mean at each TI\n\n")
        init_wsp = output_wsp.sub("init")
        basil_fit(wsp, wsp.asldata_mean_across_repeats, output_wsp=init_wsp, **extra_options)
        wsp.initmvn = output_wsp.init.finalstep.finalMVN

    # Main run on full ASL data
    wsp.log.write("\n - Doing main fit on full ASL data\n\n")
    main_wsp = output_wsp.sub("main")
    basil_fit(wsp, wsp.asldata, output_wsp=main_wsp, **extra_options)

def basil_fit(wsp, asldata, output_wsp=None, **kwargs):
    """
    Run Bayesian model fitting on ASL data

    See ``basil`` for details of workspace attributes used

    :param wsp: Workspace object
    :param asldata: AslImage object to use as input data
    :param output_wsp: Optional Workspace object for storing output files. If not specified
                       ``wsp`` is used instead
    """
    steps = basil_steps(wsp, asldata, **kwargs)
    if output_wsp is None:
        output_wsp = wsp

    prev_result = None
    for idx, step in enumerate(steps):
        step_wsp = output_wsp.sub("step%i" % (idx+1))
        desc = "Step %i of %i: %s" % (idx+1, len(steps), step.desc)
        if prev_result:
            desc += " - Initialise with step %i" % idx
        step_wsp.log.write(desc + "\n")
        result = step.run(prev_result, log=wsp.log)
        for key, value in result.items():
            setattr(step_wsp, key, value)
        prev_result = result
    output_wsp.finalstep = step_wsp
    wsp.log.write("\nEnd\n")

def basil_steps(wsp, asldata, **kwargs):
    """
    Get the steps required for a BASIL run

    This is separated for the case where an alternative process wants to run
    the actual modelling, or so that the steps can be checked prior to doing
    an actual run.

    Arguments are the same as the ``basil`` function. No workspace is required.
    """
    if not asldata:
        raise ValueError("Input ASL data is None")

    wsp.log.write("BASIL v%s\n" % __version__)
    asldata.summary(log=wsp.log)
    asldata = asldata.diff()

    # Default Fabber options for VB runs and spatial steps
    options = {
        "data" : asldata,
        "model" : "aslrest",
        "disp" : "none",
        "exch" : "mix",
        "method" : "vb",
        "noise" : "white",
        "allow-bad-voxels" : True,
        "max-iterations" : 20,
        "convergence" : "trialmode",
        "max-trials" : 10,
        "save-mean" : True,
        "save-mvn" : True,
        "save-std" : True,
    }
    for idx, ti in enumerate(asldata.tis):
        options["ti%i" % (idx+1)] = ti
        options["rpt%i" % (idx+1)] = asldata.rpts[idx]

    # Additional optional workspace arguments
    for attr in ("t1", "t1b", "bat", "tau", "casl", "slicedt", "sliceband", "FA", "mask"):
        value = getattr(wsp, attr)
        if value is not None:
            options[attr] = value

    # Any additional keyword arguments override options
    options.update(kwargs)

    # Options for final spatial step
    prior_type_spatial = "M"
    prior_type_mvs = "A"
    options_svb = {
        "method" : "spatialvb",
        "param-spatial-priors" : "N+",
        "convergence" : "maxiters",
        "max-iterations": 20,
    }

    wsp.log.write("Model (in fabber) is : %s\n" % options["model"])
    wsp.log.write("Dispersion model option is %s\n" % options["disp"])
    wsp.log.write("Compartment exchange model option is %s\n" % options["exch"])
    inferdisp = options["disp"] != "none"
    inferexch = options["exch"] != "mix"

    # Partial volume correction
    pvcorr = wsp.pgm is not None or wsp.pwm is not None
    if pvcorr:
        if wsp.pgm is None or wsp.pwm is None:
            raise ValueError("Only one partial volume map (GM / WM) was supplied for PV correctioN")
        # Need a spatial step with more iterations for the PV correction
        wsp.spatial = True
        options_svb["max-iterations"] = 200
        
    if pvcorr and not wsp.infertiss:
        raise ValueError("ERROR: PV correction is not compatible with --artonly option (there is no tissue component)")

    # Set general parameter inference and inclusion
    if wsp.infertiss:
        options["inctiss"] = True
    if wsp.inferbat:
        options["incbat"] = True
        options["inferbat"] = True # Infer in first step
    if wsp.inferart:
        options["incart"] = True
    if wsp.inferpc:
        options["incpc"] = True
    if wsp.infertau:
        options["inctau"] = True
    if wsp.infert1:
        options["inct1"] = True
    if wsp.pvcorr:
        options["incpve"] = True

    # Keep track of the number of spatial priors specified by name
    spriors = 1 

    if wsp.initmvn:
        # we are being supplied with an initial MVN
        wsp.log.write("Initial MVN being loaded %s\n" % wsp.initmvn.name)
        options["continue-from-mvn"] = wsp.initmvn
    
    # T1 image prior
    if wsp.t1im:
        spriors = _add_prior(options, spriors, "T_1", type="I", image=wsp.t1im)

    steps = []
    components = ""

    ### --- TISSUE MODULE ---
    if wsp.infertiss:
        components += " Tissue "
        options["infertiss"] = True
        step_desc = "VB - %s" % components
        if not wsp.onestep:
            steps.append(FabberStep(options, step_desc))

        # setup spatial priors ready
        spriors = _add_prior(options_svb, spriors, "ftiss", type=prior_type_spatial)

    ### --- ARTERIAL MODULE ---
    if wsp.inferart:
        components += " Arterial "
        options["inferart"] = True
        step_desc = "VB - %s" % components
        if not wsp.onestep:
            steps.append(FabberStep(options, step_desc))

        # setup spatial priors ready
        spriors = _add_prior(options_svb, spriors, "fblood", type=prior_type_mvs)

    ### --- BOLUS DURATION MODULE ---
    if wsp.infertau:
        components += " Bolus duration "
        options["infertau"] = True
        step_desc = "VB - %s" % components
        if not wsp.onestep:
            steps.append(FabberStep(options, step_desc))

    ### --- MODEL EXTENSIONS MODULE ---
    # Add variable dispersion and/or exchange parameters and/or pre-capiliary
    if inferdisp or inferexch or wsp.inferpc:
        if inferdisp:
            components += " dispersion"
            options["inferdisp"] = True
        if inferexch:
            components += " exchange"
            options["inferexch"] = True
        if wsp.inferpc:
            components += " pre-capiliary"
            options["inferpc"] = True

        step_desc = "VB - %s" % components
        if not wsp.onestep:
            steps.append(FabberStep(options, step_desc))

    ### --- T1 MODULE ---
    if wsp.infert1:
        components += " T1 "
        options["infert1"] = True
        step_desc = "VB - %s" % components
        if not wsp.onestep:
            steps.append(FabberStep(options, step_desc))

    ### --- PV CORRECTION MODULE ---
    if pvcorr:
        # setup ready for PV correction, which has to be done with spatial priors
        components += " PVE"
        options["pvcorr"] = True

        # set the image priors for the PV maps
        spriors = _add_prior(options, spriors, "pvgm", type="I", image=wsp.pgm)
        spriors = _add_prior(options, spriors, "pvwm", type="I", image=wsp.pwm)
        spriors = _add_prior(options, spriors, "fwm", type="M")

        if steps:
            # Add initialisaiton step for PV correction - ONLY if we have something to init from
            steps.append(PvcInitStep({"data" : asldata, "mask" : wsp.mask, "pgm" : wsp.pgm, "pwm" : wsp.pwm}, "PVC initialisation"))

    ### --- SPATIAL MODULE ---
    if wsp.spatial:
        step_desc = "Spatial VB - %s" % components
        options.update(options_svb)
        del options["max-trials"]

        if not wsp.onestep:
            steps.append(FabberStep(options, step_desc))

    ### --- SINGLE-STEP OPTION ---
    if wsp.onestep:
        steps.append(FabberStep(options, step_desc))
        
    if not steps:
        raise ValueError("No steps were generated - no parameters were set to be inferred")
        
    return steps

def _add_prior(options, prior_idx, param, **kwargs):
    options["PSP_byname%i" % prior_idx] = param
    for key, value in kwargs.items():
        options["PSP_byname%i_%s" % (prior_idx, key)] = value
    return prior_idx + 1

class Step(object):
    """
    A step in the Basil modelling process
    """

    def __init__(self, options, desc):
        self.options = dict(options)
        self.desc = desc

class FabberStep(Step):
    """
    A Basil step which involves running Fabber
    """

    def run(self, prev_output, log=sys.stdout):
        """
        Run Fabber, initialising it from the output of a previous step
        """
        if prev_output is not None:
            self.options["continue-from-mvn"] = prev_output["finalMVN"]

        from .wrappers import fabber
        ret = fabber(self.options, output=LOAD, progress=log)
        log.write("\n")
        return ret

class PvcInitStep(Step):
    """
    A Basil step which initialises partial volume correction
    """

    def run(self, prev_output, log=sys.stdout):
        """
        Update the MVN from a previous step to include initial estimates
        for PVC parameters
        """
        log.write("Initialising partial volume correction...\n")
        mask = self.options["mask"]
        # set the inital GM amd WM values using a simple PV correction
        wm_cbf_ratio = 0.4

        # Modified pvgm map
        #fsl.maths(pgm, " -sub 0.2 -thr 0 -add 0.2 temp_pgm")
        temp_pgm = self.options["pgm"].data
        temp_pgm[temp_pgm < 0.2] = 0.2

        # First part of correction psuedo WM CBF term
        #fsl.run("mvntool", "--input=temp --output=temp_ftiss --mask=%s --param=ftiss --param-list=step%i/paramnames.txt --val" % (mask.name, prev_step))
        #fsl.maths("temp_ftiss", "-mul %f -mul %s wmcbfterm" % (wm_cbf_ratio, pwm.name))
        prev_ftiss = prev_output["mean_ftiss"].data
        wm_cbf_term = (prev_ftiss * wm_cbf_ratio) * self.options["pwm"].data

        #fsl.maths("temp_ftiss", "-sub wmcbfterm -div temp_pgm gmcbf_init")
        #fsl.maths("gmcbf_init -mul %f wmcbf_init" % wm_cbf_ratio)
        gmcbf_init = (prev_ftiss - wm_cbf_term) / temp_pgm
        wmcbf_init = gmcbf_init * wm_cbf_ratio

        # load these into the MVN, GM cbf is always param 1
        mvn = prev_output["finalMVN"]
        from .wrappers import mvntool
        mvn = mvntool(mvn, "ftiss", output=LOAD, mask=mask, param_list="FIXME", write=True, valim=gmcbf_init, var=0.1)
        mvn = mvntool(mvn, "fwm", output=LOAD, mask=mask, param_list="FIXME", write=True, valim=wmcbf_init, var=0.1)
        log.write("DONE\n")
        return {"finalMVN" : mvn}

class BasilOptions(OptionCategory):
    """
    BASIL option category
    """

    def __init__(self, **kwargs):
        OptionCategory.__init__(self, "basil", **kwargs)

    def groups(self, parser):
        groups = []
        
        group = IgnorableOptionGroup(parser, "BASIL options", ignore=self.ignore)
        group.add_option("--optfile", "-@", dest="optfile", help="If specified, file containing additional Fabber options (e.g. --ti1=1.8)")
        groups.append(group)

        group = IgnorableOptionGroup(parser, "Extended options", ignore=self.ignore)
        group.add_option("--infertau", dest="infertau", help="Infer bolus duration", action="store_true", default=False)
        group.add_option("--inferart", dest="inferart", help="Infer macro vascular (arterial) signal component", action="store_true", default=False)
        group.add_option("--inferpc", dest="inferpc", help="Infer pre-capillary signal component", action="store_true", default=False)
        group.add_option("--infert1", dest="infert1", help="Include uncertainty in T1 values", action="store_true", default=False)
        group.add_option("--artonly", dest="artonly", help="Remove tissue component and infer only arterial component", action="store_true", default=False)
        group.add_option("--fixbat", dest="inferbat", help="Fix bolus arrival time", action="store_false", default=True)
        group.add_option("--spatial", dest="spatial", help="Add step that implements adaptive spatial smoothing on CBF", action="store_true", default=False)
        group.add_option("--fast", dest="fast", help="Faster analysis (1=faster, 2=single step", type=int, default=0)
        # FIXME not implemented
        #group.add_option("--noiseprior", help="Use an informative prior for the noise estimation", action="store_true", default=False)
        #group.add_option("--noisesd", help="Set a custom noise std. dev. for the nosie prior", type=float)
        groups.append(group)

        group = IgnorableOptionGroup(parser, "Model options", ignore=self.ignore)
        group.add_option("--disp", dest="disp", help="Model for label dispersion", default="none")
        group.add_option("--exch", dest="exch", help="Model for tissue exchange (residue function)", default="mix")
        groups.append(group)

        group = IgnorableOptionGroup(parser, "Partial volume correction / CBF estimation (enforces --spatial)", ignore=self.ignore)
        group.add_option("--pgm", dest="pgm", help="Gray matter PV map", type="image")
        group.add_option("--pwm", dest="pwm", help="White matter PV map", type="image")
        groups.append(group)

        group = IgnorableOptionGroup(parser, "Special options", ignore=self.ignore)
        group.add_option("--t1im", dest="t1im", help="Voxelwise T1 tissue estimates", type="image")
        groups.append(group)

        return groups

def main():
    """
    Entry point for BASIL command line application
    """
    try:
        parser = AslOptionParser(usage="basil -i <ASL input file> [options...]", version=__version__)
        parser.add_category(AslImageOptions())
        parser.add_category(BasilOptions())
        parser.add_category(GenericOptions())
        
        options, _ = parser.parse_args(sys.argv)
        if not options.output:
            options.output = "basil"

        if not options.asldata:
            sys.stderr.write("Input file not specified\n")
            parser.print_help()
            sys.exit(1)
        
        asldata = AslImage(options.asldata, **parser.filter(options, "image"))
        wsp = Workspace(savedir=options.output, **vars(options))
        wsp.asldata = asldata

        # Deal with --artonly
        if wsp.artonly:
            wsp.infertiss = False
            wsp.inferart = True

        # Adjust number of iterations based on fast option
        if not wsp.fast:
            num_iter, num_trials, onestep = 20, 10, False
        elif wsp.fast == 1:
            num_iter, num_trials, onestep = 5, 2, False
        elif wsp.fast == 2:
            num_iter, num_trials, onestep = 10, 5, True
        else:
            raise ValueError("Not a valid option for fast: %s" % str(wsp.fast))
        wsp.max_iterations = num_iter
        wsp.max_trials = num_trials
        wsp.onestep = onestep

        # Read in additional model options from a file
        wsp.basil_options = {}
        if wsp.optfile:
            for line in open(options.optfile):
                keyval = line.strip().rstrip("\n").lstrip("--").split("=", 1)
                key = keyval[0].strip().replace("-", "_")
                if key != "":
                    if len(keyval) == 1:
                        wsp.basil_options[key] = True
                    else:
                        wsp.basil_options[key] = keyval[1].strip()

        # Run BASIL processing, passing options as keyword arguments using **
        basil(wsp)
        
    except ValueError as exc:
        sys.stderr.write("\nERROR: " + str(exc) + "\n")
        sys.stderr.write("Use --help for usage information\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
