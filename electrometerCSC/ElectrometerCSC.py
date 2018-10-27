# This file is part of Electrometer.
#
# Developed for the LSST Telescope and Site Systems.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import asyncio
import warnings
import logging
from electrometerController.ElectrometerControllerSimulator import ElectrometerSimulator
import electrometerController.IElectrometerController as iec
import electrometerController.ElectrometerCommands as ecomm
from pythonFileReader.ConfigurationFileReaderYaml import FileReaderYaml

try:
    import SALPY_Electrometer
except ImportError:
    warnings.warn("Could not import SALPY_Electrometer; ElectrometerCSC will not work")
from salobj.python.salobj import base_csc

class ElectrometerCsc(base_csc.BaseCsc):
    """Electrometer CSC

    Parameters
    ----------
    index : `int`
        Index of Electrometer component;
    initial_state : `salobj.State`
        The initial state of the CSC. Typically one of:
        - State.ENABLED if you want the CSC immediately usable.
        - State.OFFLINE if you want full emulation of a CSC.

    """
    def __init__(self, index, initial_state=base_csc.State.STANDBY):
        if initial_state not in base_csc.State:
            raise ValueError(f"intial_state={initial_state} is not a salobj.State enum")
        super().__init__(SALPY_Electrometer, index)

        #CSC declarations
        self.summary_state = initial_state
        self.configuration = FileReaderYaml("../settingFiles", "Test", 1)

        #Loops
        self.stateCheckLoopfrequency = 0.2
        self.telemetryLoop = 0.2

        #Loggins start
        self.log = logging.getLogger(__name__)
        self.log.debug("logger initialized")
        self.log.info("Electrometer CSC initialized")

        #Events declaration
        self.evt_appliedSettingsMatchStart_data = self.evt_appliedSettingsMatchStart.DataType()
        self.evt_detailedState_data = self.evt_detailedState.DataType()
        self.evt_digitalFilterChange_data = self.evt_digitalFilterChange.DataType()
        self.evt_errorCode_data = self.evt_errorCode.DataType()
        self.evt_integrationTime_data = self.evt_integrationTime.DataType()
        self.evt_intensity_data = self.evt_intensity.DataType()
        self.evt_largeFileObjectAvailable_data = self.evt_largeFileObjectAvailable.DataType()
        self.evt_measureRange_data = self.evt_measureRange.DataType()
        self.evt_measureType_data = self.evt_measureType.DataType()
        self.evt_settingsAppliedReadSets_data = self.evt_settingsAppliedReadSets.DataType()
        self.evt_settingsAppliedSerConf_data = self.evt_settingsAppliedSerConf.DataType()
        self.evt_settingVersions_data = self.evt_settingVersions.DataType()

        #Electrometer declarations
        self.electrometer = ElectrometerSimulator()
        self.appliedSettingsMatchStart = False
        self.detailed_state = iec.ElectrometerStates.OFFLINESTATE
        self.stop_triggered = False

        #Loop initialization
        asyncio.ensure_future(self.init_stateLoop())
        asyncio.ensure_future(self.init_intensityLoop())

    def do_start(self, id_data):
        super().do_start(id_data)
        self.electrometer.updateState(iec.ElectrometerStates.DISABLEDSTATE)
        self.publish_appliedSettingsMatchStart(True)

        self.configuration.setSettingsFromLabel(id_data.data.settingsToApply)
        self.publish_settingVersions(self.configuration.getRecommendedSettings())
        self.log.debug("Start done...")

    def do_enterControl(self, id_data):
        pass

    def do_disable(self, id_data):
        super().do_disable(id_data)
        self.electrometer.updateState(iec.ElectrometerStates.DISABLEDSTATE)
        self.log.debug("Disable done...")

    def do_standby(self, id_data):
        super().do_standby(id_data)
        self.electrometer.updateState(iec.ElectrometerStates.STANDBYSTATE)
        self.appliedSettingsMatchStart = False #Reset value for the next time a start is generated
        self.log.debug("Standby done...")

    def do_enable(self, id_data):
        super().do_enable(id_data)
        self.electrometer.updateState(iec.ElectrometerStates.NOTREADINGSTATE)
        self.log.debug("Enable done...")

    def do_exitControl(self, id_data):
        super().do_exitControl(id_data)
        self.electrometer.updateState(iec.ElectrometerStates.OFFLINESTATE)
        self.log.debug("exitControl done...")

    async def do_startScanDt(self, id_data):
        values, times = await self.electrometer.readDuringTime(id_data.data.scanDuration)
        self.publishLFO_and_createFitsFile(values, times)
        self.log.debug("Start scan DT done...")

    async def do_startScan(self, id_data):
        self.electrometer.readManual()
        self.log.debug("startScan done...")

    async def do_performZeroCalib(self, id_data):
        self.electrometer.performZeroCorrection()
        self.log.debug("performZeroCalib done...")

    async def do_setDigitalFilter(self, id_data):
        self.publish_appliedSettingsMatchStart(False)
        self.electrometer.activateMedianFilter(id_data.data.activateMedFilter)
        self.electrometer.activateAverageFilter(id_data.data.activateAvgFilter)
        self.electrometer.activateFilter(id_data.data.activateFilter)
        self.publish_digitalFilterChange(self.electrometer.getAverageFilterStatus(), self.electrometer.getFilterStatus(), self.electrometer.getMedianFilterStatus())
        self.log.debug("setDigitalFilter done...")

    async def do_setIntegrationTime(self, id_data):
        self.publish_appliedSettingsMatchStart(False)
        self.electrometer.setIntegrationTime(id_data.data.intTime)
        self.publish_integrationTime(self.electrometer.getIntegrationTime())
        self.log.debug("setIntegrationTime done...")

    async def do_setMode(self, id_data):
        self.publish_appliedSettingsMatchStart(False)
        self.electrometer.setMode(self.SalModeToDeviceMode(id_data.data.mode))
        self.publish_measureType(self.electrometer.getMode())
        self.log.debug("setMode done...")

    async def do_setRange(self, id_data):
        self.publish_appliedSettingsMatchStart(False)
        self.electrometer.setRange(id_data.data.setRange)
        self.publish_measureRange(self.electrometer.getRange())
        self.log.debug("setRange done...")

    async def do_stopScan(self, id_data):
        values, times = await self.electrometer.stopReading()
        self.publishLFO_and_createFitsFile(values, times)
        self.log.debug("stopScan done...")

    async def init_stateLoop(self): 
    #Loop to check if something has changed in the device
        while True:
            self.update_deviceState(self.electrometer.getState())
            await asyncio.sleep(self.stateCheckLoopfrequency)

    async def init_intensityLoop(self):
    #Loop to publish electrometer intensity values
        while True:
            if(self.electrometer.getState() == iec.ElectrometerStates.MANUALREADINGSTATE or self.electrometer.getState() == iec.ElectrometerStates.DURATIONREADINGSTATE):
                value, unit = self.electrometer.getValue()
                self.publish_intensity(value, unit)
            await asyncio.sleep(self.telemetryLoop)

    def publish_appliedSettingsMatchStart(self, value):
        if(value == self.appliedSettingsMatchStart):
            pass
        else:
            self.evt_appliedSettingsMatchStart_data.appliedSettingsMatchStartIsTrue = value
            self.evt_appliedSettingsMatchStart.put(self.evt_appliedSettingsMatchStart_data)
            self.appliedSettingsMatchStart = value

    def publish_intensity(self, value, unit):
        self.evt_intensity_data.intensity = value
        self.evt_intensity_data.unit = unit
        self.evt_intensity_data.timestamp = self.getCurrentTime() #SALPY_Electrometer.SAL_Electrometer().getCurrentTime()
        self.evt_intensity.put(self.evt_intensity_data)

    def publish_measureRange(self, value):
        self.evt_measureRange_data = self.evt_measureRange.DataType()
        self.evt_measureRange.put(self.evt_measureRange_data)

    def publish_measureType(self, mode):
        modeToPublish = self.devideModeToSalMode(mode)
        self.evt_measureType_data = self.evt_measureType.DataType()
        self.evt_measureType_data.mode = modeToPublish
        self.evt_measureType.put(self.evt_measureType_data)

    def devideModeToSalMode(self, mode):
        if(mode == ecomm.UnitMode.CURR):
            modeToPublish = SALPY_Electrometer.Electrometer_shared_UnitToRead_Current
        elif(mode == ecomm.UnitMode.CHAR):
            modeToPublish = SALPY_Electrometer.Electrometer_shared_UnitToRead_Charge
        else:
            raise ValueError(f"Unit not implemented")
        return modeToPublish

    def SalModeToDeviceMode(self, mode):
        deviceMode = ecomm.UnitMode.CURR

        if(mode == SALPY_Electrometer.Electrometer_shared_UnitToRead_Current):
            deviceMode = ecomm.UnitMode.CURR
        elif(mode == SALPY_Electrometer.Electrometer_shared_UnitToRead_Charge):
            deviceMode == ecomm.UnitMode.CHAR
        else:
            raise ValueError(f"Unit not implemented")
        return deviceMode

    def publish_integrationTime(self, integrationTime):
        self.evt_integrationTime_data = self.evt_integrationTime.DataType()
        self.evt_integrationTime_data.intTime = integrationTime
        self.evt_integrationTime.put(self.evt_integrationTime_data)

    def publish_digitalFilterChange(self, activateAvgFilter, activateFilter, activateMedFilter):
        self.evt_digitalFilterChange_data = self.evt_digitalFilterChange.DataType()
        self.evt_digitalFilterChange_data.activateAverageFilter = activateAvgFilter
        self.evt_digitalFilterChange_data.activateFilter = activateFilter
        self.evt_digitalFilterChange_data.activateMedianFilter = activateMedFilter
        self.evt_digitalFilterChange.put(self.evt_digitalFilterChange_data)

    def update_deviceState(self, newState):
        if(newState == self.detailed_state):
            return
        self.detailed_state = self.electrometer.getState()
        if(self.detailed_state == iec.ElectrometerStates.DISABLEDSTATE):
            self.evt_detailedState_data.detailedState = SALPY_Electrometer.Electrometer_shared_DetailedState_DisabledState
        elif(self.detailed_state == iec.ElectrometerStates.ENABLEDSTATE):
            self.evt_detailedState_data.detailedState = SALPY_Electrometer.Electrometer_shared_DetailedState_EnabledState
        elif(self.detailed_state == iec.ElectrometerStates.FAULTSTATE):
            self.evt_detailedState_data.detailedState = SALPY_Electrometer.Electrometer_shared_DetailedState_FaultState
        elif(self.detailed_state == iec.ElectrometerStates.OFFLINESTATE):
            self.evt_detailedState_data.detailedState = SALPY_Electrometer.Electrometer_shared_DetailedState_OfflineState
        elif(self.detailed_state == iec.ElectrometerStates.STANDBYSTATE):
            self.evt_detailedState_data.detailedState = SALPY_Electrometer.Electrometer_shared_DetailedState_StandbyState
        elif(self.detailed_state == iec.ElectrometerStates.MANUALREADINGSTATE):
            self.evt_detailedState_data.detailedState = SALPY_Electrometer.Electrometer_shared_DetailedState_ManualReadingState  
        elif(self.detailed_state == iec.ElectrometerStates.DURATIONREADINGSTATE):
            self.evt_detailedState_data.detailedState = SALPY_Electrometer.Electrometer_shared_DetailedState_SetDurationReadingState 
        elif(self.detailed_state == iec.ElectrometerStates.CONFIGURINGSTATE):
            self.evt_detailedState_data.detailedState = SALPY_Electrometer.Electrometer_shared_DetailedState_ConfiguringState
        elif(self.detailed_state == iec.ElectrometerStates.NOTREADINGSTATE):
            self.evt_detailedState_data.detailedState = SALPY_Electrometer.Electrometer_shared_DetailedState_NotReadingState
        elif(self.detailed_state == iec.ElectrometerStates.READINGBUFFERSTATE):
            self.evt_detailedState_data.detailedState = SALPY_Electrometer.Electrometer_shared_DetailedState_ReadingBufferState
        self.evt_detailedState.put(self.evt_detailedState_data)

    def getCurrentTime(self):
        return self.salinfo.manager.getCurrentTime()

    def publishLFO_and_createFitsFile(self, values, times):
        pass

    def publish_largeFileObjectAvailable(self, url, generator, version, checkSum, mimeType, byteSize, id):
        self.evt_largeFileObjectAvailable_data.url = url
        self.evt_largeFileObjectAvailable_data.generator = generator
        self.evt_largeFileObjectAvailable_data.version = version
        self.evt_largeFileObjectAvailable_data.checkSum = checkSum
        self.evt_largeFileObjectAvailable_data.mimeType = mimeType
        self.evt_largeFileObjectAvailable_data.byteSize = byteSize
        self.evt_largeFileObjectAvailable_data.id = id

        self.evt_largeFileObjectAvailable.put(self.evt_largeFileObjectAvailable_data)

    def publish_settingsAppliedReadSets(self,filterActive,avgFilterActive,inputRange,integrationTime,medianFilterActive,mode):
        self.evt_settingsAppliedReadSets_data.filterActive = filterActive
        self.evt_settingsAppliedReadSets_data.avgFilterActive = avgFilterActive
        self.evt_settingsAppliedReadSets_data.inputRange = inputRange
        self.evt_settingsAppliedReadSets_data.integrationTime = integrationTime
        self.evt_settingsAppliedReadSets_data.medianFilterActive =medianFilterActive
        self.evt_settingsAppliedReadSets_data.mode = mode
        self.evt_settingsAppliedReadSets.put(self.evt_settingsAppliedReadSets_data)

    def publish_settingsAppliedSerConf(self,visaResource,baudRate,parity,dataBits,stopBits,flowControl,termChar):
        self.evt_settingsAppliedSerConf_data.visaResource = visaResource
        self.evt_settingsAppliedSerConf_data.baudRate = baudRate
        self.evt_settingsAppliedSerConf_data.parity = parity
        self.evt_settingsAppliedSerConf_data.dataBits = dataBits
        self.evt_settingsAppliedSerConf_data.stopBits = stopBits
        self.evt_settingsAppliedSerConf_data.flowControl = flowControl
        self.evt_settingsAppliedSerConf_data.termChar = termChar
        self.evt_settingsAppliedSerConf.put(self.evt_settingsAppliedSerConf_data)

    def publish_settingVersions(self, recommendedSettingVersion):
        self.evt_settingVersions_data.recommendedSettingVersion = recommendedSettingVersion
        self.evt_settingVersions.put(self.evt_settingVersions_data)