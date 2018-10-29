import electrometerController.ElectrometerCommands as ec
from pythonCommunicator.SerialCommunicator import SerialCommunicator
from pythonFileReader.ConfigurationFileReaderYaml import FileReaderYaml
import electrometerController.IElectrometerController as iec
from time import time
from asyncio import sleep
import asyncio #Test only, remove later....
import time as timetSleep #Test only, remove later....
import re

class ElectrometerController(iec.IElectrometerController):

    def __init__(self):
        self.mode = ec.UnitMode.CURR
        self.range = 0.1
        self.integrationTime = 0.01
        self.state = iec.ElectrometerStates.STANDBYSTATE
        self.medianFilterActive = False
        self.filterActive = False
        self.avgFilterActive = False
        self.connected = False
        self.lastValue = 0
        self.readFreq = 0.01
        self.stopReadingValue = False
        self.configurationDelay = 0.1
        self.startAndEndScanValues = [[0,0], [0,0]] #[temperature, unit]
        self.autoRange = False

        self.commands = ec.ElectrometerCommand()
        self.serialPort = None
        self.state = iec.ElectrometerStates.STANDBYSTATE
        self.lastValue = 0
        self.stopReadingValue = False

    def connect(self):
        self.serialPort.connect()

    def disconnect(self):
        self.serialPort.disconnect()

    def isConnected(self):
        return self.serialPort.isConnected()

    def configureCommunicator(self, port, baudrate, parity, stopbits, bytesize, byteToRead=1024, dsrdtr=False, xonxoff=False, timeout=2, termChar="\n"):
        self.serialPort = SerialCommunicator(port=port, baudrate=baudrate, parity=parity, stopbits=stopbits, bytesize=bytesize, byteToRead=byteToRead, dsrdtr=dsrdtr, xonxoff=xonxoff, timeout=timeout, termChar=termChar)

    def getHardwareInfo(self):
        self.serialPort.sendMessage(self.commands.getHardwareInfo())
        return self.serialPort.getMessage()

    def performZeroCorrection(self):
        self.verifyValidState(iec.CommandValidStates.performZeroCorrectionValidStates)
        self.updateState(iec.ElectrometerStates.CONFIGURINGSTATE)

        self.serialPort.sendMessage(self.commands.enableZeroCheck(True))
        self.serialPort.sendMessage(self.commands.setMode(self.mode))
        self.serialPort.sendMessage(self.commands.setRange(self.autoRange, self.range, self.mode))
        self.serialPort.sendMessage(self.commands.enableZeroCorrection(True))
        self.serialPort.sendMessage(self.commands.enableZeroCheck(False))

        self.updateState(iec.ElectrometerStates.NOTREADING)

    async def readBuffer(self):
        self.verifyValidState(iec.CommandValidStates.readBufferValidStates)
        self.updateState(iec.ElectrometerStates.READINGBUFFERSTATE)
        start = time()
        dt = 0
        response = ""
        self.serialPort.sendMessage(self.commands.stopReadingBuffer())
        self.serialPort.sendMessage(self.commands.readBuffer())
        while(dt < 600): #Can't stay reading for longer thatn 10 minutes....
            await sleep(self.readFreq)
            temporaryResponse = self.serialPort.getMessage()
            response += temporaryResponse
            print(temporaryResponse)
            dt = time() - start
            if(temporaryResponse.endswith(self.serialPort.termChar) or temporaryResponse == "" ): #Check if termination character is present
                break

        values, times, temperatures, units = self.parseGetValuesBuffer(response)
        self.updateState(iec.ElectrometerStates.NOTREADINGSTATE)
        return values, times, temperatures, units

    def readManual(self):
        self.verifyValidState(iec.CommandValidStates.readManualValidStates)
        self.state = iec.ElectrometerStates.MANUALREADINGSTATE
        self.stopReadingValue = False
        self.restartBuffer()
        self.updateLastAndEndValue(iec.InitialEndValue.INITIAL)

    def updateLastAndEndValue(self, InitialEncIdex : iec.InitialEndValue):
        value, time, temperature, unit = self.getValue()
        self.startAndEndScanValues[InitialEncIdex.value] = [temperature, unit]

    async def stopReading(self):
        self.verifyValidState(iec.CommandValidStates.stopReadingValidStates)
        self.stopReadingValue = True
        self.updateLastAndEndValue(iec.InitialEndValue.END)
        values, times, temperatures, units = await self.readBuffer()
        return values, times

    def startStoringToBuffer(self):
        self.serialPort.sendMessage(self.commands.alwaysRead())

    def stopStoringToBuffer(self):
        self.serialPort.sendMessage(self.commands.stopReadingBuffer())

    async def readDuringTime(self, timeValue):
        self.verifyValidState(iec.CommandValidStates.readDuringTimeValidStates)
        self.updateState(iec.ElectrometerStates.DURATIONREADINGSTATE)
        start = time()
        dt = 0
        values = []
        self.restartBuffer()
        while(dt < timeValue):
            sleep(self.readFreq)
            dt = time() - start
        self.stopStoringToBuffer()
        values, times, temperatures, units = await self.readBuffer()
        self.updateState(iec.ElectrometerStates.NOTREADINGSTATE)
        return values, times

    def updateState(self, newState):
        self.state = newState

    def getState(self):
        return self.state

    def getMode(self):
        self.serialPort.sendMessage(self.commands.getMode())
        modeStr = self.serialPort.getMessage()
        if(str(modeStr).__contains__("VOLT")):
            mode = ec.UnitMode.VOLT
        if(str(modeStr).__contains__("CURR")):
            mode = ec.UnitMode.CURR
        if(str(modeStr).__contains__("CHAR")):
            mode = ec.UnitMode.CHAR
        else:
            mode = ec.UnitMode.RES
        self.mode = mode
        return mode

    def getRange(self):
        self.serialPort.sendMessage(self.commands.getRange(self.mode))
        self.range = float(self.serialPort.getMessage())
        return self.range

    def getValue(self):
        self.serialPort.sendMessage(self.commands.getMeasure(ec.readingOption.LATEST))
        response = self.serialPort.getMessage()
        self.lastValue, time, temperature, unit = self.parseGetValues(response)
        return self.lastValue, time, temperature, unit

    def getIntegrationTime(self):
        self.serialPort.sendMessage(self.commands.getIntegrationTime(self.mode))
        self.integrationTime = float(self.serialPort.getMessage())
        return self.integrationTime

    def setIntegrationTime(self, integrationTime, skipState=False):
        self.verifyValidState(iec.CommandValidStates.setIntegrationTimeValidStates, skipState)
        self.state.value = iec.ElectrometerStates.CONFIGURINGSTATE
        self.serialPort.sendMessage(self.commands.integrationTime(self.mode, integrationTime))
        self.state.value = iec.ElectrometerStates.NOTREADING
        self.integrationTime = integrationTime

    def getErrorList(self):
        errorCodes, errorMessages = [], []
        for i in range(100): #Maximum of 100 errors
            self.serialPort.sendMessage(self.commands.getLastError())
            reponse = self.serialPort.getMessage()
            if(len(reponse)==0 or reponse.__contains__("No Error")): #break if there are no more errors in the queue (empty response)
                break
            errors = self.parseErrorString(reponse)
            errorCodes.append(errors[0])
            errorMessages.append(errors[1])
        return errorCodes, errorMessages

    def setMode(self, mode, skipState=False):
        self.verifyValidState(iec.CommandValidStates.setModeValidStates, skipState)
        self.state.value = iec.ElectrometerStates.CONFIGURINGSTATE
        self.serialPort.sendMessage(self.commands.setMode(self.mode))
        self.state.value = iec.ElectrometerStates.NOTREADING
        self.mode = mode
        return self.mode

    def setRange(self, range, skipState=False):
        self.verifyValidState(iec.CommandValidStates.setRangeValidStates, skipState)
        auto = True if range<0 else False
        self.state.value = iec.ElectrometerStates.CONFIGURINGSTATE
        self.serialPort.sendMessage(self.commands.setRange(auto, range, self.mode))
        self.state.value = iec.ElectrometerStates.NOTREADING
        self.range = range
        self.autoRange = auto
        return self.range

    def activateMedianFilter(self, activate, skipState=False):
        self.verifyValidState(iec.CommandValidStates.activateMedianFilterValidStates, skipState)
        self.state.value = iec.ElectrometerStates.CONFIGURINGSTATE
        self.serialPort.sendMessage(self.commands.activateFilter(self.mode, ec.Filter.MED, activate))
        self.state.value = iec.ElectrometerStates.NOTREADING
        self.medianFilterActive = activate
        return activate

    def activateAverageFilter(self, activate, skipState=False):
        self.verifyValidState(iec.CommandValidStates.activateAverageFilterValidStates, skipState)
        self.state.value = iec.ElectrometerStates.CONFIGURINGSTATE
        self.serialPort.sendMessage(self.commands.activateFilter(self.mode, ec.Filter.AVER, activate))
        self.state.value = iec.ElectrometerStates.NOTREADING
        self.avgFilterActive = activate
        return activate

    def activateFilter(self, activate, skipState=False):
        self.verifyValidState(iec.CommandValidStates.activateFilterValidStates, skipState)
        self.activateMedianFilter(activate)
        self.activateAverageFilter(activate)
        self.filterActive = activate
        return activate

    def getAverageFilterStatus(self):
        self.serialPort.sendMessage(self.commands.getAvgFilterStatus(self.mode))
        self.avgFilterActive = True if self.serialPort.getMessage().__contains__("ON") else False
        return self.avgFilterActive

    def getMedianFilterStatus(self):
        self.serialPort.sendMessage(self.commands.getMedFilterStatus(self.mode))
        self.medianFilterActive = True if self.serialPort.getMessage().__contains__("ON") else False
        return self.medianFilterActive

    def getFilterStatus(self):
        self.serialPort.sendMessage(self.commands.getAvgFilterStatus(self.mode))
        self.avgFilterActive = True if self.serialPort.getMessage().__contains__("ON") else False

        self.serialPort.sendMessage(self.commands.getMedFilterStatus(self.mode))
        self.medianFilterActive = True if self.serialPort.getMessage().__contains__("ON") else False
        return (self.medianFilterActive or self.avgFilterActive)

    def restartBuffer(self):
        self.serialPort.sendMessage(self.commands.clearBuffer())
        self.serialPort.sendMessage(self.commands.formatTrac(channel=True, timestamp=True, temperature=False))
        self.serialPort.sendMessage(self.commands.setBufferSize(50000))

        self.serialPort.sendMessage(self.commands.selectDeviceTimer(0.001))
        self.serialPort.sendMessage(self.commands.nextRead())

    def getLastScanValues(self):
        #Returns values stored at the beggining of the manual and time scan
        return self.startAndEndScanValues

    def parseErrorString(self, errorMessage):
        totalError = errorMessage.split(",")
        errorCode, errorStr = totalError[0], totalError[1]
        return errorCode, errorStr

    def parseGetValues(self, response):
        regexNumbers = "[-+]?[.]?[\d]+(?:,\d\d\d)*[\.]?\d*(?:[eE][-+]?\d+)?"
        regexStrings = "(?!E+)[a-zA-Z]+"
        intensity, time, temperature, unit = [], [], [], []
        unsortedValues = list(map(float, re.findall(regexNumbers, response)))
        intensity, time, temperature, unit = unsortedValues[0], unsortedValues[1], 0, regexStrings[0]
        return intensity, time, temperature, unit

    def parseGetValuesBuffer(self, response):
        regexNumbers = "[-+]?[.]?[\d]+(?:,\d\d\d)*[\.]?\d*(?:[eE][-+]?\d+)?"
        regexStrings = "(?!E+)[a-zA-Z]+"
        intensity, time, temperature, unit = [], [], [], []
        unsortedValues = list(map(float, re.findall(regexNumbers, response)))
        unsortedStrValues = re.findall(regexStrings, response)
        i = 0
        while i < 50000:
            intensity.append(unsortedValues[i])
            time.append(unsortedValues[i+1])
            temperature.append(0)
            unit.append(unsortedStrValues[i])
            i+=3
            if(i>=len(unsortedValues)-2):
                break

        return intensity, time, temperature, unit

    def getAll(self):
        return(self.serialPort.getMessage())

    def reset(self):
        print(self.getHardwareInfo())

    def getBufferQuantity(self):
        self.serialPort.sendMessage(self.commands.getBufferQuantity())
        return int(self.serialPort.getMessage())

