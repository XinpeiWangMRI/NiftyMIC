#!/usr/bin/python

##
# \file StackRegistrationBase.py
# \brief      Abstract class containing the shared attributes and functions for
#             registrations of stack of slices
#
# \author     Michael Ebner (michael.ebner.14@ucl.ac.uk)
# \date       Nov 2016


## Import libraries
from abc import ABCMeta, abstractmethod
import sys
import SimpleITK as sitk
import itk
import numpy as np
import time
from datetime import timedelta
from scipy.optimize import least_squares

## Import modules
import utilities.SimpleITKHelper as sitkh
import utilities.PythonHelper as ph
import base.Stack as st
import utilities.ParameterNormalization as pn


##
#       Abstract class containing the shared attributes and functions for
#             registrations of stack of slices
# \date       2016-11-06 16:58:15+0000
#
class StackRegistrationBase(object):
    __metaclass__ = ABCMeta

    ##
    #       Constructor
    # \date       2016-11-06 16:58:43+0000
    #
    # \param      self                The object
    # \param      stack               The stack to be aligned as Stack object
    # \param      reference           The reference used for alignment as Stack
    #                                 object
    # \param      use_stack_mask      Use stack mask for registration, bool
    # \param      use_reference_mask  Use reference mask for registration, bool
    # \param      use_verbose         Verbose output, bool
    #
    def __init__(self, stack=None, reference=None, use_stack_mask=False, use_reference_mask=False, use_verbose=False, initializer_type="identity", interpolator="Linear", alpha_neighbour=1, alpha_reference=1, alpha_parameter=1, use_parameter_normalization=False, optimizer_nfev_max=50, optimizer_loss="soft_l1", optimizer_method="trf"):

        ## Set Fixed and reference stacks
        if stack is not None:
            self._stack = st.Stack.from_stack(stack)
            self._N_slices = self._stack.get_number_of_slices()
        else:
            self._stack = None

        if reference is not None:
            self._reference = st.Stack.from_stack(reference)
        else:
            self._reference = None
    
        ## Set booleans to use mask            
        self._use_stack_mask = use_stack_mask
        self._use_reference_mask = use_reference_mask

        ## Parameters for solver
        self._optimizer_nfev_max = optimizer_nfev_max
        self._optimizer_loss = optimizer_loss
        self._optimizer_method = optimizer_method

        ## Verbose computation
        self._use_verbose = use_verbose

        ## Initializer type
        self._get_initial_transforms_and_parameters = {
            "identity"  :   self._get_initial_transforms_and_parameters_identity,
            "moments"   :   self._get_initial_transforms_and_parameters_geometry_moments,
            "geometry"  :   self._get_initial_transforms_and_parameters_geometry_moments
        }
        self._dictionary_initializer_type_sitk = {
            "identity"  :   None,
            "moments"   :   "MOMENTS",
            "geometry"  :   "GEOMETRY"
        }
        self._initializer_type = initializer_type

        ## Interpolator
        self._interpolator = interpolator
        self._interpolator_sitk = eval("sitk.sitk" + self._interpolator)

        ## Set weights for cost function of each term/residual
        self._alpha_neighbour = alpha_neighbour
        self._alpha_reference = alpha_reference
        self._alpha_parameter = alpha_parameter

        self._use_parameter_normalization = use_parameter_normalization


    ##
    #       Sets stack/reference/target image.
    # \date       2016-11-06 16:59:14+0000
    #
    # \param      self   The object
    # \param      stack  stack as Stack object
    #
    def set_stack(self, stack):
        self._stack = st.Stack.from_stack(stack)
        self._N_slices = self._stack.get_number_of_slices()

    def get_stack(self):
        return self._stack


    ##
    #       Sets reference stack.
    # \date       2016-11-06 17:00:50+0000
    #
    # \param      self       The object
    # \param      reference  reference stack as Stack object
    #
    def set_reference(self, reference):
        self._reference = st.Stack.from_Stack(reference)

    def get_reference(self):
        return self._reference


    ##
    #       Specify whether mask of stack image shall be used for
    #             registration
    # \date       2016-11-06 17:03:05+0000
    #
    # \param      self  The object
    # \param      flag  The flag as boolean
    #
    def use_stack_mask(self, flag):
        self._use_stack_mask = flag


    ##
    #       Specify whether mask of reference image shall be used for
    #             registration
    # \date       2016-11-06 17:03:05+0000
    #
    # \param      self  The object
    # \param      flag  The flag as boolean
    #
    def use_reference_mask(self, flag):
        self._use_reference_mask = flag


    ##
    #       Specify whether output information shall be produced.
    # \date       2016-11-06 17:07:01+0000
    #
    # \param      self  The object
    # \param      flag  The flag
    #
    def use_verbose(self, flag):
        self._use_verbose = flag


    ##
    #       Perform parameter normalization for optimizer
    # \date       2016-11-17 16:10:14+0000
    #
    # \param      self  The object
    # \param      flag  The flag, boolean
    #
    def use_parameter_normalization(self, flag):
        self._use_parameter_normalization = flag


    ##
    #       Sets the initializer type used to initialize the registration
    # \date       2016-11-08 00:20:29+0000
    #
    # The initial transform can either be the identity ('None') or be based on
    # the moments ('moments') or geometry ('geometry') of the stack and
    # reference image.
    #
    # \param      self              The object
    # \param      initializer_type  The initializer type to be either 'None',
    #                               'moments' or 'geometry'
    #
    def set_initializer_type(self, initializer_type):
        if initializer_type not in ["identity", "moments", "geometry"]:
            raise ValueError("Error: centered transform initializer type can only be 'identity', moments' or 'geometry'")

        self._initializer_type = initializer_type

    def get_initializer_type(self):
        return self._initializer_type


    ##
    #       Sets the interpolator used for resampling operations
    # \date       2016-11-08 16:19:33+0000
    #
    # \param      self          The object
    # \param      interpolator  The interpolator as string
    #
    def set_interpolator(self, interpolator):
        self._interpolator = interpolator
        self._interpolator_sitk = eval("sitk.sitk" + self._interpolator)

    def get_interpolator(self):
        return self._interpolator


    ##
    #       Sets the weight for the residual between the slice neighbours
    # \date       2016-11-10 00:59:59+0000
    #
    # \param      self             The object
    # \param      alpha_neighbour  The alpha neighbour
    #
    def set_alpha_neighbour(self, alpha_neighbour):
        self._alpha_neighbour = alpha_neighbour

    def get_alpha_neighbour(self):
        return self._alpha_neighbour

    ##
    #       Sets the weight for the residual between the slice neighbours
    #             and the reference
    # \date       2016-11-10 01:00:41+0000
    #
    # \param      self             The object
    # \param      alpha_reference  The alpha reference
    #
    def set_alpha_reference(self, alpha_reference):
        self._alpha_reference = alpha_reference

    def get_alpha_reference(self):
        return self._alpha_reference


    ##
    #       Sets the weight for the residual between the slice neighbours
    # \date       2016-11-10 01:01:18+0000
    #
    # \param      self             The object
    # \param      alpha_parameter  The alpha parameter
    #
    # \return     { description_of_the_return_value }
    #
    def set_alpha_parameter(self, alpha_parameter):
        self._alpha_parameter = alpha_parameter

    def get_alpha_parameter(self):
        return self._alpha_parameter


    ##
    #       Set maximum number of function evaluations for least_squares
    #             optimizer
    # \date       2016-11-10 19:24:35+0000
    #
    # \param      self      The object
    # \param      optimizer_nfev_max  The nfev maximum
    # 
    # \see        https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html#scipy.optimize.least_squares
    #
    def set_optimizer_nfev_max(self, optimizer_nfev_max):
        self._optimizer_nfev_max = optimizer_nfev_max

    def get_optimizer_nfev_max(self):
        return self._optimizer_nfev_max


    ##
    #       Sets the optimizer_loss function for least_squares optimizer
    # \date       2016-11-17 16:07:29+0000
    #
    # \param      self  The object
    # \param      optimizer_loss  The optimizer_loss in ["linear", "soft_l1", "huber", "cauchy",
    #                   "arctan"]
    #
    # \see        https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html#scipy.optimize.least_squares
    #
    def set_optimizer_loss(self, optimizer_loss):
        if optimizer_loss not in ["linear", "soft_l1", "huber", "cauchy", "arctan"]:
            raise ErrorValue("Optimizer optimizer_loss for least_squares must either be 'linear', 'soft_l1', 'huber', 'cauchy' or 'arctan'.")

        self._optimizer_loss = optimizer_loss

    def get_optimizer_loss(self):
        return self._optimizer_loss


    ##
    #       Sets the optimizer_method for least_squares optimizer
    # \date       2016-11-17 16:08:37+0000
    #
    # \param      self    The object
    # \param      optimizer_method  The optimizer_method in ["trf", "lm", "dogbox"]
    #
    # \see        https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html#scipy.optimize.least_squares
    #
    def set_optimizer_method(self, optimizer_method):
        if optimizer_method not in ["trf", "lm", "dogbox"]:
            raise ValueError("Optimizer optimizer_method for least_squares must either be 'trf', 'lm' or 'dogbox'.")

        self._optimizer_method = optimizer_method

    def get_optimizer_method(self):
        return self._optimizer_method


    ##
    #       Gets the parameters estimated by registration algorithm.
    # \date       2016-11-06 17:05:38+0000
    #
    # \param      self  The object
    #
    # \return     The parameters.
    #
    def get_parameters(self):
        return np.array(self._parameters)


    ##
    #       Gets the registered stack.
    # \date       2016-11-08 19:44:15+0000
    #
    # \param      self  The object
    #
    # \return     The registered stack with motion corrected slices
    #
    def get_corrected_stack(self):
        return st.Stack.from_stack(self._stack_corrected)


    ##
    #       Gets the parameters information.
    # \date       2016-11-08 14:56:12+0000
    #
    # \param      self  The object
    #
    # \return     The parameters information as list of strings describing the
    #             meaning of each element in parameters
    #
    # @abstractmethod
    # def get_parameters_info(self):
    #     pass


    ##
    #       Gets the registraton transform sitk.
    # \date       2016-11-06 17:10:14+0000
    #
    # \param      self  The object
    #
    # \return     The registraton transforms sitk.
    #
    def get_slice_transforms_sitk(self):
        return np.array(self._slice_transforms_sitk)


    ##
    #       Print statistics associated to performed registration
    # \date       2016-11-06 17:07:56+0000
    #
    # \param      self  The object
    #
    def print_statistics(self):
        # print("\nStatistics for performed registration:" %(self._reg_type))
        # if self._elapsed_time_sec < 0:
        #     raise ValueError("Error: Elapsed time has not been measured. Run 'run_reconstruction' first.")
        # else:
        print("\tElapsed time = %s" %(self._elapsed_time))
        # print("\tell^2-residual sum_k ||M_k(A_k x - y_k||_2^2 = %.3e" %(self._residual_ell2))
        # print("\tprior residual = %.3e" %(self._residual_prior))


    ##
    #       Run the registration
    # \date       2016-11-10 01:39:03+0000
    #
    # \param      self  The object
    #
    def run_registration(self):

        if self._optimizer_method in ["lm"]:
            verbose = 1
            if self._optimizer_loss not in ["linear"]:
                self._optimizer_loss = "linear"
                print("Optimizer method 'lm' only supports 'linear' loss function. ")
                
        else:        
            verbose = 2

        # jac = '2-point'
        jac = '3-point'
        x_scale = 1.0 #or array
        # x_scale = 'jac' #or array

        ## Initialize registration pipeline         
        self._run_registration_pipeline_initialization()

        ## Parameter normalization
        if self._use_parameter_normalization:
            parameter_normalization = pn.ParameterNormalization(self._parameters)
            parameter_normalization.compute_normalization_coefficients()
            coefficients = parameter_normalization.get_normalization_coefficients()

            ## Use absolute mean for normalization
            scale = abs(np.array(coefficients[0]))

            ## scale could be zero (like for rotation)
            scale[np.where(scale==0)] = 1

            if self._use_verbose:
                print("Normalization parameters:")
                print scale

            x_scale = np.tile(scale, self._parameters.shape[0])


        ## HACK
        self._transforms_2D_itk = [None]*self._N_slices
        for i in range(0, self._N_slices):
            self._transforms_2D_itk[i] = self._new_transform_itk[self._transform_type]()
            self._transforms_2D_itk[i].SetParameters(itk.OptimizerParameters[itk.D](self._transforms_2D_sitk[i].GetParameters()))
            self._transforms_2D_itk[i].SetFixedParameters(itk.OptimizerParameters[itk.D](self._transforms_2D_sitk[i].GetFixedParameters()))


        ## Get cost function and its Jacobian w.r.t. the parameters
        fun = self._get_residual_call()
        jac = self._get_jacobian_residual_call()

        # Non-linear least-squares optimizer_method:
        self._print_info_text()
        time_start = ph.start_timing()
        res = least_squares(fun=fun, x0=self._parameters0_vec.flatten(), method=self._optimizer_method, loss=self._optimizer_loss, max_nfev=self._optimizer_nfev_max, verbose=verbose, x_scale=x_scale) 
        # res = least_squares(fun=fun, jac=jac, x0=self._parameters0_vec.flatten(), method=self._optimizer_method, loss=self._optimizer_loss, max_nfev=self._optimizer_nfev_max, verbose=verbose, x_scale=x_scale) # res = least_squares(fun=fun, x0=parameters0, optimizer_method='lm', optimizer_loss='linear', verbose=1)
        # res = least_squares(fun=fun, x0=parameters0, optimizer_method='lm', optimizer_loss='linear', verbose=1)
        # res = least_squares(fun=fun, x0=parameters0, optimizer_method='dogbox', optimizer_loss='linear', verbose=2) 
        self._elapsed_time = ph.stop_timing(time_start)

        ## Get and reshape final transform parameters for each slice
        self._parameters = res.x.reshape(self._parameters.shape)

        ## Denormalize parameters
        # self._parameters = self._parameter_normalizer.denormalize_parameters(self._parameters)

        # if self._use_verbose:
        #     print("Final values = ")
        #     print self._parameters

        ## Apply motion correction and compute slice transforms
        self._apply_motion_correction()

    def _print_info_text(self):
        print("Minimization via least_squares solver")
        print("\tMethod: " + self._optimizer_method)
        print("\tLoss: " + self._optimizer_loss)
        print("\tMaximum number of function evaluations: " + str(self._optimizer_nfev_max))
        print("\tStack mask used: " + str(self._use_stack_mask))
        if self._reference is not None:
            print("\tReference mask used: " + str(self._use_reference_mask))
        print("\tRegularization parameters: %s (reference), %s (neighbour), %s (parameter)" %(str(self._alpha_reference), str(self._alpha_neighbour), str(self._alpha_parameter)))


    ##
    #       optimizer_Method to initialize the registration with all
    #             precomputations which can be done before the actual
    #             optimization.
    # \date       2016-11-10 01:37:13+0000
    #
    # \param      self  The object
    #
    @abstractmethod
    def _run_registration_pipeline_initialization(self):
        pass


    ##
    #       Gets the residual call used for the least_squares
    #             optimization routine
    # \date       2016-11-10 01:38:08+0000
    #
    # \param      self  The object
    #
    # \return     The residual call.
    #
    @abstractmethod
    def _get_residual_call(self):
        pass


    ##
    #       Gets the initial parameters in case of identity transform.
    # \date       2016-11-08 15:06:54+0000
    #
    # \param      self  The object
    #
    # \return     The initial parameters corresponding to identity transform.
    #
    @abstractmethod
    def _get_initial_transforms_and_parameters_identity(self):
        pass


    ##
    #       Gets the initial parameters for either 'geometry' or
    #             'moments'.
    # \date       2016-11-08 15:08:07+0000
    #
    # \param      self  The object
    #
    # \return     The initial parameters corresponding to 'geometry' or
    #             'moments'.
    #
    @abstractmethod
    def _get_initial_transforms_and_parameters_geometry_moments(self):
        pass


    ##
    #       optimizer_Method that applies the obtained registration transforms to
    #             update the slices positions and to get the affine slice
    #             transforms capturing the performed motion correction.
    # \date       2016-11-10 01:34:42+0000
    #
    # \param      self  The object
    #
    @abstractmethod
    def _apply_motion_correction(self):
        pass


