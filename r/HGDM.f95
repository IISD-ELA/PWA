! The Hysteretic and Gatekeeping Depressions Model (HGDM)
! Developed by Kevin Shook and changed by Mohamed Ahmed to be used in hydrologic models
! HYPE and MESH
!Copyright (C) 2021  Kevin Shook & Mohamed Ahmed

! This is the main subroutine of the algorithm.
! v01: Currently, the HGDM handles the complxeities of the small depression
! that are represented using the linear form. No Big Ponds (gatekeeping) function.

!**************************************************************************

!    __       __    ______  _______ .__   __.      _______. _______
!   |  |     |  |  /      ||   ____||  \ |  |     /       ||   ____|
!   |  |     |  | |  ,----'|  |__   |   \|  |    |   (----`|  |__
!   |  |     |  | |  |     |   __|  |  . `  |     \   \    |   __|
!   |  `----.|  | |  `----.|  |____ |  |\   | .----)   |   |  |____
!   |_______||__|  \______||_______||__| \__| |_______/    |_______|
!
!  This program is free software; you can redistribute it and/or modify
!  it under the terms of the GNU General Public License as published by
!  the Free Software Foundation; either version 3 of the License, or
!  (at your option) any later version.
!
!  This program is distributed in the hope that it will be useful,
!  but WITHOUT ANY WARRANTY; without even the implied warranty of
!  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
!  GNU General Public License for more details.
!
!  You should have received a copy of the GNU General Public License
!  along with this program; if not, write to the Free Software
!  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
!  MA 02110-1301, USA.
!**************************************************************************
module HGDM


contains

!MAIN SUBROUTINE

! Converted from R -> Fortran by Kevin Shook, June 2020
!
! This function applies net precip to water, and calculates runoff depth
! Because the areas of application (of direct precip., evap, and runoff)
! depend on the storage

! The function arguments are mostly dimensionless fractions or
! areal-average depths, so that that they are more easily shared among
! basins. However, they need to be dimensionalised within the function.

! Arguments:
! current_depth - state variable. Current depth of water (m) ) in
! depressional storage

! delta_depth - flux. Change of depth of water to be applied (m)
! directly to the small pond water area (i.e. direct precip or evap.),
! either positive or negative

! runoff_depth - flux. Depth of upland runoff running into
! small ponds (m)

! max_depth - state parameter. Maximum depth of water (m) that can be
! stored in the small ponds

! max_water_area_frac - state parameter. Max possible areal fraction of
! the small ponds basin/GRU that can be covered with water.

! application_iterations - subroutine execution parameter. Number of
! iterations used for applying fluxes

! area_mult, area_power - scaling parameters. Multiplier and exponent
! relating small pond water area to water depth.

! vol_frac - state variable. Fraction of maximum storage volume filled
! by water. Updated by subroutine.

! area_frac - state variable. Fraction of maximum water area covered
! by water. Updated by subroutine.

! contrib_frac - state variable. Fracation of the GRU/basin affected
! by small ponds, which is contributing runoff. Updated by subroutine.

! depth - state variable. Current depth of water (m) on the GRU/basin.
! Updated by subroutine.

! outflow_depth - flux. Depth of outflow (m) from small ponds. Output
! by subroutine.

subroutine small_depressions_delta_water(current_depth, delta_depth, runoff_depth, contrib_frac, &
                            max_depth, max_water_area_frac, & !application_iterations,
                            area_mult, area_power, vol_frac, area_frac, &
                            depth, outflow_depth)

! arguments
  real :: current_depth, delta_depth, contrib_frac, max_depth
  real ::  max_water_area_frac, area_mult, area_power, vol_frac, area_frac
  real :: depth, outflow_depth
  !integer :: application_iterations

! internal variables
  real :: current_vol_frac, iteration_delta, iteration_runoff, iteration_contrib_frac
  real :: iteration_area_frac, total_outflow_depth, water_area_frac, upland_area_frac
  real :: delta_depth_applied !, current_depth

  current_vol_frac = current_depth / max_depth  ! current fractional storage volume
  iteration_delta = delta_depth !/ application_iterations
  iteration_runoff = runoff_depth !/ application_iterations
  iteration_contrib_frac = contrib_frac
  iteration_area_frac = small_depression_water_frac_area(current_vol_frac, area_mult, area_power)
  total_outflow_depth = 0.0

  ! check to see if worth doing
  if ((iteration_delta /= 0.0) .or. (iteration_runoff > 0.0)) then
    ! apply fluxes iteratively, changing the areas of application
    !do i = 1, application_iterations
      water_area_frac = max_water_area_frac * iteration_area_frac   ! basin/HRU areal fraction of water
      upland_area_frac = 1.0 - water_area_frac
      delta_depth_applied = (iteration_delta * water_area_frac)  + &
        iteration_runoff * upland_area_frac * (1.0 - iteration_contrib_frac)
      !MIA debug
      !write(*,*) delta_depth_applied !iteration_delta * water_area_frac, iteration_runoff * upland_area_frac * (1.0 - iteration_contrib_frac)

      current_depth = current_depth + delta_depth_applied

      ! check to see if max depth of storage is exceeded
      if (current_depth > max_depth) then
      ! max depth is exceeded, so there will be outflows
        excess_depth = max(current_depth - max_depth, 0.0)
        current_depth = max_depth
        iteration_contrib_frac = 1.0
        total_outflow_depth = total_outflow_depth + &
          (excess_depth * water_area_frac) + &
          (iteration_runoff * upland_area_frac * iteration_contrib_frac)

      else
      ! max depth is not exceeded, so no outflows from depressions, but there is outflow
      !from upland area
        excess_depth = 0.0
        total_outflow_depth = total_outflow_depth + &
          (iteration_runoff * upland_area_frac * iteration_contrib_frac)
        ! update contributing fraction for next iteration
        iteration_contrib_frac = small_depression_contrib_frac(iteration_contrib_frac, current_depth, &
                                                   delta_depth_applied, max_depth)
      endif

      ! update state variables
      current_vol_frac = current_depth / max_depth
      iteration_area_frac = small_depression_water_frac_area(current_vol_frac, area_mult, area_power)
    !enddo

    vol_frac = current_depth  / max_depth
    area_frac = iteration_area_frac
    contrib_frac = iteration_contrib_frac
    depth = current_depth
    outflow_depth = total_outflow_depth

  else
    ! nothing to do - return initial values
    vol_frac = current_depth / max_depth
    area_frac = iteration_area_frac
    contrib_frac = iteration_contrib_frac
    depth = current_depth
    outflow_depth = 0.0
  endif

end subroutine







!==========================================================================

! F U N C T I O N S

!------------------------------

! A function for calculating the water area of parameterized small ponds
! Converted from R -> Fortran by Kevin Shook, June 2020

! The function uses a simple exponential relationship to estimate the
! fractional water area from the fractional water volume.

! The fractional water area is the fraction of the maximum possible
! water area occupied by small depressions in a basin/grid/GRU which
! is occupied by water.

! Arguments:
! vol_frac - state variable. The fraction of the depressional
! storage in a basin/grid/GRU which is occupied by water.

! mult - calculation parameter. The multiplier in the relationship
! between the volume and area fractions. Optional.


! power - calculation parameter. The exponent in the relationship
! between the volume and area fractions. Optional.

! If mult or power are not specified, the function will use values
! estimated from Smith Creek Research Basin. These will NOT be
! appropriate for your location.


function  small_depression_water_frac_area (vol_frac, mult, power)
  real :: small_depression_water_frac_area
  ! arguments
  real, intent(in) :: vol_frac
  real, optional :: mult, power

  ! internal variables
  real :: water_frac

  ! check for parameter values - if not specified use SCRB values
  if (.not. present(mult)) then
    mult = 1.0058485
  endif

  if (.not. present(power)) then
    power = 1.5198
  endif

  ! use simple exponential equation to calculate water areal fraction
  if (vol_frac <= 0.0) then
    water_frac = 0.0
  else
    water_frac = mult * vol_frac ** power
  endif

  small_depression_water_frac_area = max(min(water_frac, 1.0), 0.0)

end function small_depression_water_frac_area

!------------------------------

! A function for calculating the contributing fraction of
! parameterized small depressions

! Converted from R -> Fortran by Kevin Shook, June 2020

! This function uses a simple linear form of the
! hysteretic relationship between the volumetric water fraction
! and the contributing fraction of a basin/grid/GRU.

! In this function, the contributing fraction refers to the
! areal fraction of a basin/grid/GRU which can contribute
! overland flow to its outlet, whether or not flow is actually
! occurring.

! The contributing fraction is estimated inside the space defined
! by the ranges of the volume fraction (x) and
! the contributing fraction (y), i.e. between (0,0) and (1,1).

! If there is evaporation, then the contributing fraction is zero.

! If there is an addition of water, then the contributing fraction
! is estimated from the current value, on a trajectory to (1,1).

! Note that because the contributing fraction of the small depressions
! varies continuously with the application of water, this function
! needs to be called repeatedly, as water is added to the depressions.
! This is shown in the subroutine small_ponds_delta_water.

! Arguments:
! current_contribfrac - state variable. Current version of the
! contributing fraction of small depressions in the basin/grid/GRU

! current_depth - state variable. Depth of water (m) in the fraction
! of the basin/grid/GRU occupied by small depressions.

! delta_depth - flux. Depth of water (m) applied to the fraction of the
! basin/grid/GRU occupied by small depressions.

! max-depth - limiting value. Maximum possible depth of water (m) in
! the fraction of the basin/grid/GRU occupied by small depressions.



function small_depression_contrib_frac(current_contrib_frac, &
                                  current_depth, delta_depth, max_depth)
  real :: small_depression_contrib_frac

  ! arguments
  real, intent(in) :: current_contrib_frac, current_depth, delta_depth, max_depth

  ! internal variables
  real :: new_contribfrac, volfrac, volfrac_delta, slope

  if (delta_depth == 0.0 ) then
    new_contribfrac = current_contrib_frac
  else
    if (delta_depth < 0.0) then
      ! evaporation
      new_contribfrac = 0.0
    else
      ! direct precip and/or runoff
      volfrac = current_depth / max_depth  ! current fractional water vol
      volfrac_delta = delta_depth / max_depth ! change in water vol frac

      ! calculate the slope of the line connecting the current point
      ! to (1, 1)
      slope = (1.0 - current_contrib_frac) / (1.0 - volfrac)
      slope = max(slope, 0.0)  ! slope can't be < 0 for addition of water

      ! using the slope, calculate the new contributing fraction
      new_contribfrac = current_contrib_frac + (volfrac_delta * slope)
    endif
  endif

  small_depression_contrib_frac = min(max(new_contribfrac, 0.0), 1.0)

end function small_depression_contrib_frac

!------------------------------
!==========================================================================


end module HGDM