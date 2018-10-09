oxasl
=====

Python library for ASL analysis using the FSLPY wrapper library for FSL

Output structure
----------------

 - ``input/``      : Original unchanged input data
 - ``corrected/``  : Corrected input data. Generated by ``apply_corrections``
 - ``calib/``      : Related to the calibration process (M0 maps, reference region mask etc)
 - ``basil/``      : Related to BASIL model fitting
 - ``reg/``        : Related to registration (ASL->structural, calib->ASL etc)
 - ``distcorr/``   : Related to distortion correction (fieldmap / topup)
 - ``structural/`` : Related to structural data (segmentation etc)
 - ``moco/``       : Related to motion correction
 - ``rois/``       : Mask generation
 - ``native/``     : Native (ASL) space output
 - ``report/``     : Output report
 
Plans/ideas
-----------

 - Do we need the IgnorableOptionGroup, OptionCategory gubbins? 

 - Does cblip/cref belong in calibration - should be corrections?

 - Should independently register calib/cblip/cref to ASL - they may be in different spaces

 - Workspace to automatically create AslImage object

