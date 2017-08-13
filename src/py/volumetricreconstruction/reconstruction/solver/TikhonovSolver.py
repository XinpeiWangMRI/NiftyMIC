#!/usr/bin/python

# \file TikhonovSolver.py
#  \brief Implementation to get an approximate solution of the inverse problem
#  \f$ y_k = A_k x \f$ for each slice \f$ y_k,\,k=1,\dots,K \f$
#  by using Tikhonov-regularization
#
#  \author Michael Ebner (michael.ebner.14@ucl.ac.uk)
#  \date July 2016

# Import libraries
import os
import sys
import itk
import SimpleITK as sitk
import numpy as np
import time
from scipy.optimize import minimize

import numericalsolver.TikhonovLinearSolver as tk
import numericalsolver.LinearOperators as linop
import pythonhelper.SimpleITKHelper as sitkh
import pythonhelper.PythonHelper as ph

# Import modules
from volumetricreconstruction.reconstruction.solver.Solver import Solver


# This class implements the framework to iteratively solve
#  \f$ \vec{y}_k = A_k \vec{x} \f$ for every slice \f$ \vec{y}_k,\,k=1,\dots,K \f$
#  via Tikhonov-regularization via an augmented least-square approach
#  where \f$A_k=D_k B_k W_k\in\mathbb{R}^{N_k}\f$ denotes the combined warping, blurring and downsampling
#  operation, \f$ M_k \f$ the masking operator and \f$G\f$ represents either
#  the identity matrix \f$I\f$ (zeroth-order Tikhonov) or
#  the (flattened, stacked vector) gradient
#  \f$ \nabla  = \begin{pmatrix} D_x \\ D_y \\ D_z \end{pmatrix} \f$
#  (first-order Tikhonov).
#  The minimization problem reads
#  \f[
#       \text{arg min}_{\vec{x}} \Big( \sum_{k=1}^K \frac{1}{2} \Vert M_k (\vec{y}_k - A_k \vec{x} )\Vert_{\ell^2}^2
#                       + \frac{\alpha}{2}\,\Vert G\vec{x} \Vert_{\ell^2}^2 \Big)
#       =
#       \text{arg min}_{\vec{x}} \Bigg( \Bigg\Vert
#           \begin{pmatrix} M_1 A_1 \\ M_2 A_2 \\ \vdots \\ M_K A_K \\ \sqrt{\alpha} G \end{pmatrix} \vec{x}
#           - \begin{pmatrix} M_1 \vec{y}_1 \\ M_2 \vec{y}_2 \\ \vdots \\ M_K \vec{y}_K \\ \vec{0} \end{pmatrix}
#       \Bigg\Vert_{\ell^2}^2 \Bigg)
#  \f]
#  By defining the shorthand
#  \f[
#   MA := \begin{pmatrix} M_1 A_1 \\ M_2 A_2 \\ \vdots \\ M_K A_K \end{pmatrix}\in\mathbb{R}^{\sum_k N_k} \quad\text{and}\quad
#   M\vec{y} := \begin{pmatrix} M_1 \vec{y}_1 \\ M_2 \vec{y}_2 \\ \vdots \\ M_K \vec{y}_K \end{pmatrix}\in\mathbb{R}^{\sum_k N_k}
#  \f]
#  the problem can be compactly written as
#  \f[
#       \text{arg min}_{\vec{x}} \Bigg( \Bigg\Vert
#           \begin{pmatrix} MA \\ \sqrt{\alpha} G \end{pmatrix} \vec{x}
#           - \begin{pmatrix} M\vec{y} \\ \vec{0} \end{pmatrix}
#       \Bigg\Vert_{\ell^2}^2 \Bigg)
#  \f]
#  with \f$ G\in\mathbb{R}^N \f$ in case of \f$G=I\f$ or
#  \f$G\in\mathbb{R}^{3N}\f$ in case of \f$G\f$ representing the gradient.
#  \see \p itkAdjointOrientedGaussianInterpolateImageFilter of \p ITK
#  \see \p itOrientedGaussianInterpolateImageFunction of \p ITK
class TikhonovSolver(Solver):

    ##
    # Constructor
    # \date          2016-08-01 23:00:04+0100
    #
    # \param         self                   The object
    # \param         stacks                 list of Stack objects containing
    #                                       all stacks used for the
    #                                       reconstruction
    # \param[in,out] reconstruction         Stack object containing the current
    #                                       estimate of the reconstruction
    #                                       volume (used as initial value +
    #                                       space definition)
    # \param         alpha_cut              Cut-off distance for Gaussian
    #                                       blurring filter
    # \param         alpha                  regularization parameter, scalar
    # \param         iter_max               number of maximum iterations,
    #                                       scalar
    # \param         reg_type               Type of Tikhonov regualrization,
    #                                       i.e. TK0 or TK1 for either zeroth-
    #                                       or first order Tikhonov
    # \param         minimizer              Type of minimizer used to solve
    #                                       minimization problem, possible
    #                                       types: 'lsmr', 'lsqr', 'L-BFGS-B' #
    # \param         deconvolution_mode     Either "full_3D" or
    #                                       "only_in_plane". Indicates whether
    #                                       full 3D or only in-plane
    #                                       deconvolution is considered
    # \param         data_loss              The loss
    # \param         huber_gamma            The huber gamma
    # \param         predefined_covariance  The predefined covariance
    # \param         verbose                The verbose
    #
    def __init__(self,
                 stacks,
                 reconstruction,
                 alpha_cut=3,
                 alpha=0.03,
                 iter_max=10,
                 reg_type="TK1",
                 minimizer="lsmr",
                 deconvolution_mode="full_3D",
                 data_loss="linear",
                 huber_gamma=1.345,
                 predefined_covariance=None,
                 verbose=1,
                 ):

        # Run constructor of superclass
        Solver.__init__(self,
                        stacks=stacks,
                        reconstruction=reconstruction,
                        alpha_cut=alpha_cut,
                        alpha=alpha,
                        iter_max=iter_max,
                        minimizer=minimizer,
                        deconvolution_mode=deconvolution_mode,
                        data_loss=data_loss,
                        huber_gamma=huber_gamma,
                        predefined_covariance=predefined_covariance,
                        verbose=verbose)

        # Settings for optimizer
        self._reg_type = reg_type

        # Residual values after optimization
        self._residual_prior = None
        self._residual_ell2 = None

    #
    # Set type of regularization. It can be either 'TK0' or 'TK1'
    # \date       2017-07-25 15:19:17+0100
    #
    # \param      self      The object
    # \param      reg_type  Either 'TK0' or 'TK1', string
    #
    # \return     { description_of_the_return_value }
    #
    def set_regularization_type(self, reg_type):
        self._reg_type = reg_type

    # Get chosen type of regularization.
    #  \return regularization type as string
    def get_regularization_type(self):
        return self._reg_type

    # Compute statistics associated to performed reconstruction
    def compute_statistics(self):
        recon_nda_vec = sitk.GetArrayFromImage(
            self._reconstruction.sitk).flatten()

        self._residual_ell2 = self._get_residual_ell2(recon_nda_vec)
        self._residual_prior = self._get_residual_prior[
            self._reg_type](recon_nda_vec)

    ##
    # Gets the final cost after optimization
    # \date       2016-11-25 18:33:00+0000
    #
    # \param      self  The object
    #
    # \return     The final cost.
    #
    def get_final_cost(self):

        if self._residual_ell2 is None or self._residual_prior is None:
            self.compute_statistics()

        return self._residual_ell2 + self._alpha*self._residual_prior

    ##
    #       Gets the setting specific filename indicating the information
    #             used for the reconstruction step
    # \date       2016-11-17 15:41:58+0000
    #
    # \param      self    The object
    # \param      prefix  The prefix as string
    #
    # \return     The setting specific filename as string.
    #
    def get_setting_specific_filename(self, prefix="SRR_"):

        # Build filename
        filename = prefix
        filename += "stacks" + str(len(self._stacks))
        if self._alpha > 0:
            filename += "_" + self._reg_type
        filename += "_" + self._minimizer
        if self._data_loss not in ["linear"] or \
                self._minimizer in ["L-BFGS-B"]:
            filename += "_" + self._data_loss
            if self._data_loss in ["huber"]:
                filename += str(self._huber_gamma)
        filename += "_alpha" + str(self._alpha)
        filename += "_itermax" + str(self._iter_max)

        # Replace dots by 'p'
        filename = filename.replace(".", "p")

        return filename

    ##
    # Run the reconstruction algorithm based on Tikhonov regularization
    # \date       2016-07-29 12:35:01+0100
    # \post       self._reconstruction is updated with new volume and can be
    #             fetched by \p get_recon
    #
    # \param      self  The object
    # \param      provide_initial_value  Use reconstruction volume during
    #                                    initialization as initial value, boolean.
    #                                    Otherwise, assume zero initial vale.
    #
    # \return     { description_of_the_return_value }
    #
    def _run_reconstruction(self):

        if self._reg_type not in ["TK0", "TK1"]:
            raise ValueError(
                "Error: regularization type can only be either 'TK0' or 'TK1'")

        self._print_info_text()

        # Get operators
        A = self.get_A()
        A_adj = self.get_A_adj()
        b = self.get_b()
        x0 = self.get_x0()
        x_scale = x0.max()
        if self._reg_type == "TK0":
            B = lambda x: x.flatten()
            B_adj = lambda x: x.flatten()

        elif self._reg_type == "TK1":
            spacing = np.array(self._reconstruction.sitk.GetSpacing())
            linear_operators = linop.LinearOperators3D(spacing=spacing)
            grad, grad_adj = linear_operators.get_gradient_operators()

            X_shape = self._reconstruction_shape
            Z_shape = grad(x0.reshape(*X_shape)).shape

            B = lambda x: grad(x.reshape(*X_shape)).flatten()
            B_adj = lambda x: grad_adj(x.reshape(*Z_shape)).flatten()

        # Run reconstruction
        solver = tk.TikhonovLinearSolver(
            A=A,
            A_adj=A_adj,
            B=B,
            B_adj=B_adj,
            b=b,
            x0=x0,
            x_scale=x_scale,
            alpha=self._alpha,
            data_loss=self._data_loss,
            verbose=self._verbose,
            minimizer=self._minimizer,
            iter_max=self._iter_max,
            bounds=(0, np.inf),
        )
        solver.run()

        # Get computational time
        self._computational_time = solver.get_computational_time()

        # After reconstruction: Update member attribute
        self._reconstruction.itk = self._get_itk_image_from_array_vec(
            solver.get_x(), self._reconstruction.itk)
        self._reconstruction.sitk = sitkh.get_sitk_from_itk_image(
            self._reconstruction.itk)

    def _print_info_text(self):

        ph.print_subtitle("Tikhonov Solver:")
        ph.print_info("Chosen regularization type: ", newline=False)
        if self._reg_type in ["TK0"]:
            print("Zeroth-order Tikhonov")

        else:
            print("First-order Tikhonov")

        if self._deconvolution_mode in ["only_in_plane"]:
            ph.print_info("(Only in-plane deconvolution is performed)")

        elif self._deconvolution_mode in ["predefined_covariance"]:
            ph.print_info("(Predefined covariance used: cov = diag(%s))"
                          % (np.diag(self._predefined_covariance)))

        if self._data_loss in ["huber"]:
            ph.print_info("Loss function: %s (gamma = %g)" %
                          (self._data_loss, self._huber_gamma))
        else:
            ph.print_info("Loss function: %s" % (self._data_loss))

        ph.print_info("Regularization parameter: " + str(self._alpha))

        # Non-linear loss function requires use of L-BFGS-B
        if self._data_loss not in ["linear"] and \
                self._minimizer not in ["L-BFGS-B"]:
            ph.print_info("Note, selected minimizer '%s' cannot be used."
                          " Non-linear loss function requires L-BFGS-B."
                          % (self._minimizer))
            self._minimizer = "L-BFGS-B"

        ph.print_info("Minimizer: " + self._minimizer)
        ph.print_info(
            "Maximum number of iterations: " + str(self._iter_max))
        # ph.print_info("Tolerance: %.0e" %(self._tolerance))