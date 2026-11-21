from iqdbc.car import Bus, get_safety_config, structs, uds
from iqdbc.car.hyundai.hyundaicanfd import CanBus
from iqdbc.car.hyundai.values import HyundaiFlags, HyundaiFlagsIQ, CAR, DBC, HyundaiSafetyFlags, HyundaiSafetyFlagsIQ
from iqdbc.car.hyundai.radar_interface import RADAR_START_ADDR
from iqdbc.car.interfaces import CarInterfaceBase
from iqdbc.car.disable_ecu import disable_ecu
from iqdbc.car.hyundai.carcontroller import CarController
from iqdbc.car.hyundai.carstate import CarState
from iqdbc.car.hyundai.radar_interface import RadarInterface

ButtonType = structs.CarState.ButtonEvent.Type
Ecu = structs.CarParams.Ecu

# Cancel button can sometimes be ACC pause/resume button, main button can also enable on some cars
ENABLE_BUTTONS = (ButtonType.accelCruise, ButtonType.decelCruise, ButtonType.cancel, ButtonType.mainCruise)


class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController
  RadarInterface = RadarInterface

  DRIVABLE_GEARS = (structs.CarState.GearShifter.sport, structs.CarState.GearShifter.manumatic)

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "hyundai"

    # "LKA steering" if LKAS or LKAS_ALT messages are seen coming from the camera.
    # Generally means our LKAS message is forwarded to another ECU (commonly ADAS ECU)
    # that finally retransmits our steering command in LFA or LFA_ALT to the MDPS.
    # "LFA steering" if camera directly sends LFA to the MDPS
    cam_can = CanBus(None, fingerprint).CAM
    lka_steering = not (ret.flags & HyundaiFlags.CAMERA_SCC) and (0x50 in fingerprint[cam_can] or 0x110 in fingerprint[cam_can])
    CAN = CanBus(None, fingerprint, lka_steering)

    if lka_steering:
      ret.flags |= HyundaiFlags.CANFD_LKA_STEER_MSG.value

    if ret.flags & HyundaiFlags.CANFD:
      # Shared configuration for CAN-FD cars
      ret.alphaLongitudinalAvailable = not (ret.flags & HyundaiFlags.CANFD_NO_RADAR_DISABLE)
      if lka_steering and Ecu.adas not in [fw.ecu for fw in car_fw]:
        # this needs to be figured out for cars without an ADAS ECU
        ret.alphaLongitudinalAvailable = False

      if 0x1ba in fingerprint[CAN.ECAN]:
        ret.flags |= HyundaiFlags.HAS_BSM.value

      # Check if the car is hybrid. Only HEV/PHEV cars have 0xFA on E-CAN.
      if 0xFA in fingerprint[CAN.ECAN]:
        ret.flags |= HyundaiFlags.HYBRID.value

      if lka_steering:
        if 0x110 in fingerprint[CAN.CAM]:
          ret.flags |= HyundaiFlags.CANFD_LKA_STEER_MSG_ALT.value
      else:
        # no LKA steering
        if 0x1cf not in fingerprint[CAN.ECAN]:
          ret.flags |= HyundaiFlags.CANFD_ALT_BUTTONS.value
        if not ret.flags & HyundaiFlags.CANFD_RADAR_SCC:
          ret.flags |= HyundaiFlags.CANFD_CAMERA_SCC.value

      # Some LKA steering cars have alternative messages for gear checks
      # ICE cars do not have 0x130; GEARS message on 0x40 or 0x70 instead
      if 0x130 not in fingerprint[CAN.ECAN]:
        if 0x40 not in fingerprint[CAN.ECAN]:
          ret.flags |= HyundaiFlags.CANFD_ALT_GEARS_2.value
        else:
          ret.flags |= HyundaiFlags.CANFD_ALT_GEARS.value

      cfgs = [get_safety_config(structs.CarParams.SafetyModel.hyundaiCanfd), ]
      if CAN.ECAN >= 4:
        cfgs.insert(0, get_safety_config(structs.CarParams.SafetyModel.noOutput))
      ret.safetyConfigs = cfgs

      if ret.flags & HyundaiFlags.CANFD_LKA_STEER_MSG:
        if ret.flags & HyundaiFlags.CANFD_LKA_STEER_MSG_ALT:
          ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.CANFD_LKA_STEER_MSG_ALT.value
      if ret.flags & HyundaiFlags.CANFD_ALT_BUTTONS:
        ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.CANFD_ALT_BUTTONS.value
      if ret.flags & HyundaiFlags.CANFD_CAMERA_SCC:
        ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.CAMERA_SCC.value

    else:
      # Shared configuration for non CAN-FD cars
      ret.alphaLongitudinalAvailable = not (ret.flags & (HyundaiFlags.LEGACY | HyundaiFlags.UNSUPPORTED_LONGITUDINAL))
      camera_scc = bool(ret.flags & HyundaiFlags.CAMERA_SCC)
      classic_offset = cam_can - 2 if camera_scc and 0x421 not in fingerprint[2] and 0x421 in fingerprint[cam_can] else 0
      bsm_bus = CAN.ECAN if ret.flags & HyundaiFlags.CAN_CANFD_HYBRID else classic_offset
      if 0x58b in fingerprint[bsm_bus]:
        ret.flags |= HyundaiFlags.HAS_BSM.value

      # Send LFA message on cars with HDA
      if 0x485 in fingerprint[classic_offset + 2]:
        ret.flags |= HyundaiFlags.SEND_LFA.value

      # These cars use the FCA11 message for the AEB and FCW signals, all others use SCC12
      if 0x38d in fingerprint[classic_offset] or 0x38d in fingerprint[classic_offset + 2]:
        ret.flags |= HyundaiFlags.USE_FCA.value

      if ret.flags & HyundaiFlags.LEGACY:
        # these cars require a special panda safety mode due to missing counters and checksums in the messages
        ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.hyundaiLegacy)]
      else:
        cfgs = [get_safety_config(structs.CarParams.SafetyModel.hyundai), ]
        safety_bus = classic_offset if camera_scc else CAN.ECAN
        if safety_bus >= 4:
          cfgs.insert(0, get_safety_config(structs.CarParams.SafetyModel.noOutput))
        ret.safetyConfigs = cfgs

      if ret.flags & HyundaiFlags.CAMERA_SCC:
        ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.CAMERA_SCC.value

      if ret.flags & HyundaiFlags.CAN_CANFD_HYBRID:
        ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.CAN_CANFD_HYBRID.value

      # These cars have the LFA button on the steering wheel
      if 0x391 in fingerprint[bsm_bus]:
        ret.flags |= HyundaiFlags.HAS_LDA_BUTTON.value

    if ret.flags & HyundaiFlags.CANFD_LKA_STEER_MSG:
      ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.CANFD_LKA_STEER_MSG.value

    # Common lateral control setup

    ret.centerToFront = ret.wheelbase * 0.4
    ret.steerActuatorDelay = 0.1
    ret.steerLimitTimer = 0.4
    CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    if ret.flags & HyundaiFlags.ALT_LIMITS:
      ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.ALT_LIMITS.value

    if ret.flags & HyundaiFlags.ALT_LIMITS_2:
      ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.ALT_LIMITS_2.value

    # Common longitudinal control setup

    ret.radarUnavailable = RADAR_START_ADDR not in fingerprint[1] or Bus.radar not in DBC[ret.carFingerprint]
    ret.openpilotLongitudinalControl = alpha_long and ret.alphaLongitudinalAvailable
    ret.pcmCruise = not ret.openpilotLongitudinalControl
    ret.longitudinalActuatorDelay = 0.5
    ret.radarTimeStep = 0.05
    ret.startingState = False
    ret.vEgoStarting = 0.1
    ret.startAccel = 1.0
    ret.longitudinalTuning.kpBP = [0.]
    ret.longitudinalTuning.kpV = [1.]
    ret.longitudinalTuning.kf = 1.0

    if ret.openpilotLongitudinalControl:
      ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.LONG.value
    if ret.flags & HyundaiFlags.HYBRID:
      ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.HYBRID_GAS.value
    elif ret.flags & HyundaiFlags.EV:
      ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.EV_GAS.value
    elif ret.flags & HyundaiFlags.FCEV:
      ret.safetyConfigs[-1].safetyParam |= HyundaiSafetyFlags.FCEV_GAS.value

    # Car specific configuration overrides

    if candidate == CAR.KIA_OPTIMA_G4_FL:
      ret.steerActuatorDelay = 0.2

    # Palisade/Telluride 2023-24 without HDA II have not been validated
    if candidate == CAR.HYUNDAI_PALISADE_2023 and not lka_steering:
      ret.dashcamOnly = True

    return ret

  @staticmethod
  def _get_params_iq(stock_cp, ret, candidate, fingerprint, car_fw, alpha_long, is_release_iq, docs):
    del candidate, car_fw, alpha_long, is_release_iq, docs
    actuation = ret.longitudinalActuation
    actuation.jerkControl = actuation.JerkControl.nativeAsymmetric
    actuation.maxJerkUp = actuation.maxJerkDown = 5.0
    if not stock_cp.flags & HyundaiFlags.CANFD and stock_cp.openpilotLongitudinalControl:
      actuation.comfortBand = actuation.ComfortBand.asymmetric
    lda_bus = CanBus(None, fingerprint, stock_cp.flags & HyundaiFlags.CANFD_LKA_STEER_MSG).ECAN
    if stock_cp.flags & HyundaiFlags.CAMERA_SCC:
      lda_bus = CanBus(stock_cp).ECAN
    if not stock_cp.flags & HyundaiFlags.CANFD and 0x391 in fingerprint[lda_bus]:
      ret.flags |= HyundaiFlagsIQ.HAS_LFA_BUTTON
      ret.iqSafetyFlags |= HyundaiSafetyFlagsIQ.HAS_LDA_BUTTON
    return ret

  @staticmethod
  def init(CP, CP_IQ, can_recv, can_send, communication_control=None):
    # 0x80 silences response
    if communication_control is None:
      communication_control = bytes([uds.SERVICE_TYPE.COMMUNICATION_CONTROL, 0x80 | uds.CONTROL_TYPE.DISABLE_RX_DISABLE_TX, uds.MESSAGE_TYPE.NORMAL])

    if CP.openpilotLongitudinalControl and not (CP.flags & (HyundaiFlags.CANFD_CAMERA_SCC | HyundaiFlags.CAMERA_SCC)):
      addr, bus = 0x7d0, CanBus(CP).ECAN if CP.flags & HyundaiFlags.CANFD else 0
      if CP.flags & HyundaiFlags.CANFD_LKA_STEER_MSG.value:
        addr, bus = 0x730, CanBus(CP).ECAN
      disable_ecu(can_recv, can_send, bus=bus, addr=addr, com_cont_req=communication_control)

    # for blinkers
    if CP.flags & HyundaiFlags.CANFD_ENABLE_BLINKERS:
      disable_ecu(can_recv, can_send, bus=CanBus(CP).ECAN, addr=0x7B1, com_cont_req=communication_control)

  @staticmethod
  def deinit(CP, can_recv, can_send):
    communication_control = bytes([uds.SERVICE_TYPE.COMMUNICATION_CONTROL, 0x80 | uds.CONTROL_TYPE.ENABLE_RX_ENABLE_TX, uds.MESSAGE_TYPE.NORMAL])
    CarInterface.init(CP, None, can_recv, can_send, communication_control)
