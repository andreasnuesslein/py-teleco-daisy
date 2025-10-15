from time import sleep
from typing import Any, Literal

import requests
from pydantic import BaseModel, ConfigDict

base_url = "https://tmate.telecoautomation.com/"


class DaisyStatus(BaseModel):
    """for /status-device-list"""

    idInstallationDeviceStatusitem: int
    idDevicetypeStatusitemModel: int
    statusitemCode: str
    statusItem: str
    statusValue: str
    lowlevelStatusitem: None | str = None


class DaisyInstallation(BaseModel):
    activetimer: str
    firmwareVersion: str
    idInstallation: int
    idInstallationDevice: int
    instCode: str
    instDescription: str
    installationOrder: int
    latitude: float | None
    longitude: float | None
    weekend: str | None  # list[str]
    workdays: str | None  # list[str]

    def __str__(self):
        return f"DaisyInstallation fw{self.firmwareVersion}"


class DaisyBaseDevice(BaseModel):
    activetimer: str
    deviceCode: str
    deviceIndex: int
    deviceOrder: int
    directOnly: str | None = None
    favorite: str
    feedback: str
    idDevicemodel: int
    idDevicetype: int
    idInstallationDevice: int
    label: str
    remoteControlCode: str


class DaisyDevice(DaisyBaseDevice):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    client: "TelecoDaisy"
    installation: DaisyInstallation

    def __str__(self):
        return f'{self.__class__.__name__} "{self.label}"'

    def command(self, params: dict):
        return self.client.feed_the_commands(
            installation=self.installation,
            commandsList=[
                {
                    "deviceCode": str(self.deviceIndex),
                    "idInstallationDevice": self.idInstallationDevice,
                }
                | params
            ],
        )

    def update_state(self) -> list[DaisyStatus]:
        return self.client.status_device_list(self.installation, self)


class DaisyDeviceWithCommands(DaisyBaseDevice):
    class DeviceCommand(BaseModel):
        commandAction: str
        commandCode: str
        commandParam: str
        deviceIndex: int
        idDevicetypeCommandModel: int
        idInstallationDeviceCommand: int
        lowlevelCommand: str

    deviceCommandList: list[DeviceCommand]

    def __str__(self):
        return (
            f'DaisyDevice "{self.label}" '
            f"(deviceType: {self.idDevicetype}, deviceModel: {self.idDevicemodel})"
        )


class DaisyRoom(BaseModel):
    idInstallationRoom: int
    idRoomtype: int
    roomDescription: str
    roomOrder: int
    deviceList: list[DaisyDevice]

    def __str__(self):
        return f'DaisyRoom "{self.roomDescription}"'


class DaisyRoomWithCommands(DaisyRoom):
    deviceList: list[DaisyDeviceWithCommands]


class DaisyCover(DaisyDevice):
    is_closed: bool | None = None

    osc_map: dict[Literal["open", "stop", "close"], dict[str, Any]]

    def update_state(self):
        stati = super().update_state()
        for status in stati:
            if status.statusitemCode == "OPEN_CLOSE":
                match status.statusValue:
                    case "CLOSE":
                        self.is_closed = True
                    case "OPEN":
                        self.is_closed = False
                    case _:
                        self.is_closed = None
        return stati

    def open_cover(self):
        return self._open_stop_close("open")

    def stop_cover(self):
        self._open_stop_close("stop")

    def close_cover(self):
        self._open_stop_close("close")

    def _open_stop_close(self, open_stop_close: Literal["open", "stop", "close"]):
        return self.command(
            {"commandAction": "OPEN_STOP_CLOSE"} | self.osc_map[open_stop_close]
        )


class DaisySlatsCover(DaisyCover):
    position: int | None = None

    osc_map: dict[Literal["open", "stop", "close"], dict[str, Any]] = {
        "open": {"commandId": 94, "commandParam": "OPEN", "lowlevelCommand": "CH4"},
        "stop": {"commandId": 95, "commandParam": "STOP", "lowlevelCommand": "CH7"},
        "close": {"commandId": 96, "commandParam": "CLOSE", "lowlevelCommand": "CH1"},
    }

    def open_cover(self, percent: Literal["33", "66", "100"] | None = None):
        if percent == "100" or percent is None:
            return self._open_stop_close("open")

        percent_map = {
            "33": {"commandParam": "LEV2", "commandId": 97, "lowlevelCommand": "CH2"},
            "66": {"commandParam": "LEV3", "commandId": 98, "lowlevelCommand": "CH3"},
            "100": {"commandParam": "LEV4", "commandId": 99, "lowlevelCommand": "CH4"},
        }

        return self.command({"commandAction": "LEVEL"} | percent_map[percent])

    def update_state(self):
        stati = super().update_state()
        for status in stati:
            if status.statusitemCode == "LEVEL":
                self.position = int(status.statusValue)
        return stati


class DaisyShadeCover(DaisyCover):
    pass


class DaisyAwningCover(DaisyCover):
    pass


class DaisyLight(DaisyDevice):
    is_on: bool | None = None
    brightness: int | None = None  # from 0 to 100

    def update_state(self):
        stati = super().update_state()
        for status in stati:
            if status.statusitemCode == "POWER":
                self.is_on = status.statusValue == "ON"
        return stati

    def _turn_on(self, specific_params: dict):
        return self.command(
            {"commandAction": "POWER", "commandParam": "ON"} | specific_params
        )

    def _turn_off(self, specific_params: dict):
        return self.command(
            {"commandAction": "POWER", "commandParam": "OFF"} | specific_params
        )


class DaisyRGBLight(DaisyLight):
    rgb: tuple[int, int, int] | None = None

    def update_state(self):
        stati = super().update_state()
        for status in stati:
            if status.statusitemCode == "COLOR":
                val = status.statusValue
                self.brightness = int(val[1:4])
                self.rgb = (int(val[5:8]), int(val[9:12]), int(val[13:16]))
        return stati

    def set_rgb_and_brightness(
        self, rgb: tuple[int, int, int] | None = None, brightness: int | None = None
    ):
        if brightness is None:
            brightness = self.brightness or 0
        if 0 > brightness or brightness > 100:
            raise ValueError("Brightness must be between 0 and 100")
        if rgb is None:
            rgb = self.rgb or (255, 255, 255)
        if any((c < 0 or c > 255) for c in rgb):
            raise ValueError("Color must be between 0 and 255")

        v = f"A{brightness:03d}R{rgb[0]:03d}G{rgb[1]:03d}B{rgb[2]:03d}"

        return self.command(
            {
                "commandAction": "COLOR",
                "commandId": 137,
                "commandParam": v,
                "lowlevelCommand": None,
            }
        )

    def turn_on(self):
        return self._turn_on({"commandId": 138, "lowlevelCommand": None})

    def turn_off(self):
        return self._turn_off({"commandId": 138, "lowlevelCommand": None})


# class DaisyWhiteLight(DaisyLight):
#     def set_brightness(self, brightness: int):
#         if brightness is None:
#             brightness = self.brightness or 0
#         if 0 > brightness or brightness > 100:
#             raise ValueError("Brightness must be between 0 and 100")
#
#         v = f"A{brightness:03d}R255G255B255"
#
#         return self.command(
#             {
#                 "commandAction": "COLOR",
#                 "commandId": 146,
#                 "commandParam": v,
#                 "lowlevelCommand": "CH1",
#             }
#         )
#
#     def turn_on(self):
#         # https://github.com/andreasnuesslein/py-teleco-daisy/issues/10
#         if self.idDevicetype == 21 and self.idDevicemodel == 17:
#             return self._turn_on({"commandId": 40, "lowlevelCommand": "CH1"})
#         return self._turn_on({"commandId": 146, "lowlevelCommand": "CH1"})
#
#     def turn_off(self):
#         # https://github.com/andreasnuesslein/py-teleco-daisy/issues/10
#         if self.idDevicetype == 21 and self.idDevicemodel == 17:
#             return self._turn_off({"commandId": 41, "lowlevelCommand": "CH8"})
#         return self._turn_off({"commandId": 147, "lowlevelCommand": "CH8"})


class DaisyWhite4LevelLight(DaisyLight):
    brightness_map: dict[Literal[25, 50, 75, 100], dict[str, Any]]

    def set_brightness(self, brightness: int):
        if brightness is None:
            brightness = self.brightness or 0
        if 0 > brightness or brightness > 100:
            raise ValueError("Brightness must be between 0 and 100")

        if brightness is None or brightness == 0:
            return self.turn_off()

        if 1 <= brightness <= 37:
            vals = self.brightness_map[25]
        elif 38 <= brightness <= 62:
            vals = self.brightness_map[50]
        elif 63 <= brightness <= 87:
            vals = self.brightness_map[75]
        else:  # 76-100
            vals = self.brightness_map[100]

        return self.command({"commandAction": "LEVEL"} | vals)

    def turn_on(self):
        if self.idDevicetype == 21 and self.idDevicemodel == 17:
            return self._turn_on({"commandId": 40, "lowlevelCommand": "CH1"})
        if self.idDevicetype == 21 and self.idDevicemodel == 34:
            return self._turn_on({"commandId": 146, "lowlevelCommand": "CH1"})

        # legacy, without devicemodelmatching
        return self._turn_on({"commandId": 146, "lowlevelCommand": "CH1"})

    def turn_off(self):
        # https://github.com/andreasnuesslein/py-teleco-daisy/issues/10
        if self.idDevicetype == 21 and self.idDevicemodel == 17:
            return self._turn_off({"commandId": 41, "lowlevelCommand": "CH8"})
        if self.idDevicetype == 21 and self.idDevicemodel == 34:
            return self._turn_on({"commandId": 147, "lowlevelCommand": "CH8"})

        # legacy, without devicemodelmatching
        return self._turn_off({"commandId": 147, "lowlevelCommand": "CH8"})


class DaisyHeater4CH(DaisyDevice):
    def turn_on(self):
        return self.command(
            {
                "commandAction": "POWER",
                "commandParam": "ON",
                "lowlevelCommand": "CH1",
                "commandId": 58,
            }
        )

    def turn_off(self):
        return self.command(
            {
                "commandAction": "POWER",
                "commandParam": "OFF",
                "lowlevelCommand": "CH4",
                "commandId": 59,
            }
        )

    def set_level(self, level: Literal["50", "75", "100"]):
        if level == "50":
            cmd = {
                # "idDevicetypeCommandModel": 60,
                "commandId": 60,
                "commandParam": "LEV2",
                "lowlevelCommand": "CH3",
            }
        elif level == "75":
            cmd = {
                # "idDevicetypeCommandModel": 61,
                "commandId": 61,
                "commandParam": "LEV3",
                "lowlevelCommand": "CH2",
            }
        else:
            cmd = {
                # "idDevicetypeCommandModel": 62,
                "commandId": 62,
                "commandParam": "LEV4",
                "lowlevelCommand": "CH1",
            }

        return self.command({"commandAction": "LEVEL"} | cmd)


def create_specific_device(dev):
    match dev:
        # #1.
        case {"idDevicetype": 23, "idDevicemodel": 32}:
            return DaisyRGBLight(**dev)
        case {"idDevicetype": 24, "idDevicemodel": 27}:
            return DaisySlatsCover(**dev)

        # #4
        case {"idDevicetype": 21, "idDevicemodel": 34}:
            dev["brightness_map"] = {
                25: {
                    "commandParam": "LEV1",
                    "commandId": 141,
                    "lowlevelCommand": "CH4",
                },
                50: {
                    "commandParam": "LEV2",
                    "commandId": 142,
                    "lowlevelCommand": "CH3",
                },
                75: {
                    "commandParam": "LEV3",
                    "commandId": 143,
                    "lowlevelCommand": "CH2",
                },
                100: {
                    "commandParam": "LEV4",
                    "commandId": 144,
                    "lowlevelCommand": "CH1",
                },
            }
            return DaisyWhite4LevelLight(**dev)
        case {"idDevicetype": 21, "idDevicemodel": 17}:
            dev["brightness_map"] = {
                25: {"commandParam": "LEV1", "commandId": 42, "lowlevelCommand": "CH4"},
                50: {"commandParam": "LEV2", "commandId": 43, "lowlevelCommand": "CH3"},
                75: {"commandParam": "LEV3", "commandId": 44, "lowlevelCommand": "CH2"},
                100: {
                    "commandParam": "LEV4",
                    "commandId": 45,
                    "lowlevelCommand": "CH1",
                },
            }
            return DaisyWhite4LevelLight(**dev)

        # #23
        case {"idDevicetype": 21, "idDevicemodel": 20}:
            return DaisyHeater4CH(**dev)

        # #12
        case {"idDevicetype": 22, "idDevicemodel": 31}:
            dev["osc_map"] = {
                "open": {
                    "commandId": 111,
                    "commandParam": "OPEN",
                    "lowlevelCommand": "CH5",
                },
                "stop": {
                    "commandId": 112,
                    "commandParam": "STOP",
                    "lowlevelCommand": "CH7",
                },
                "close": {
                    "commandId": 113,
                    "commandParam": "CLOSE",
                    "lowlevelCommand": "CH8",
                },
            }
            return DaisyShadeCover(**dev)

        # #12
        case {"idDevicetype": 22, "idDevicemodel": 25}:
            dev["osc_map"] = {
                "open": {
                    "commandId": 75,
                    "commandParam": "OPEN",
                    "lowlevelCommand": "CH5",
                },
                "stop": {
                    "commandId": 76,
                    "commandParam": "STOP",
                    "lowlevelCommand": "CH7",
                },
                "close": {
                    "commandId": 77,
                    "commandParam": "CLOSE",
                    "lowlevelCommand": "CH8",
                },
            }
            return DaisyShadeCover(**dev)

        case {"idDevicetype": 22, "idDevicemodel": 21}:
            dev["osc_map"] = {
                "open": {
                    "commandId": 63,
                    "commandParam": "OPEN",
                    "lowlevelCommand": "CH5",
                },
                "stop": {
                    "commandId": 64,
                    "commandParam": "STOP",
                    "lowlevelCommand": "CH7",
                },
                "close": {
                    "commandId": 65,
                    "commandParam": "CLOSE",
                    "lowlevelCommand": "CH8",
                },
            }
            return DaisyAwningCover(**dev)

        # let's deactivate and see who's complaining
        # case {"idDevicetype": 21 | 25}:
        #     return DaisyWhiteLight(**dev)

        # I think this was #5
        # case {"idDevicetype": 22}:
        #     return DaisyAwningsCover(**dev)
        case _:
            return DaisyDevice(**dev)


class TelecoDaisy:
    idAccount: int | None = None
    idSession: str | None = None

    def __init__(self, email, password):
        self.s = requests.Session()
        self.s.auth = ("teleco", "tmate20")
        self.email = email
        self.password = password

    def _tmate20_post(self, url, json: dict | None = None) -> dict:
        payload = {"idSession": self.idSession}
        if json:
            payload |= json
        req = self.s.post(base_url + url, json=payload)
        return req.json()

    def _post(self, url, json: dict | None = None, unauth=False) -> dict:
        if unauth:
            _json = json
        else:
            _json = {"idSession": self.idSession, "idAccount": self.idAccount}
            if json:
                _json |= json
        req = self.s.post(base_url + url, json=_json)
        req_json = req.json()
        if req_json["codEsito"] != "S":
            raise Exception(req_json)
        return req_json["valRisultato"]

    def login(self):
        login = self._post(
            "teleco/services/account-login",
            {"email": self.email, "pwd": self.password},
            unauth=True,
        )
        self.idAccount = login["idAccount"]
        self.idSession = login["idSession"]

    def get_account_installation_list(self) -> list[DaisyInstallation]:
        req = self._post("teleco/services/account-installation-list")

        return [DaisyInstallation(**inst) for inst in req["installationList"]]

    def get_installation_is_active(self, installation: DaisyInstallation):
        res = self._tmate20_post(
            "teleco/services/tmate20/nodestatus/",
            {"idInstallation": installation.instCode},
        )
        return res["nodeActive"]

    def get_room_configuration_list(self, installation: DaisyInstallation):
        req = self._post(
            "teleco/services/room-configuration-list",
            {"idInstallation": installation.idInstallation},
        )
        return [DaisyRoomWithCommands(**dr) for dr in req["roomList"]]

    def get_room_list(self, installation: DaisyInstallation) -> list[DaisyRoom]:
        room_list = self._post(
            "teleco/services/room-list",
            {"idInstallation": installation.idInstallation},
        )

        rooms = []
        for room in room_list["roomList"]:
            device_list = []
            for dv in room["deviceList"]:
                dv["installation"] = installation
                dv["client"] = self
                device_list += [create_specific_device(dv)]
            rooms += [DaisyRoom(**room | {"deviceList": device_list})]

        return rooms

    def status_device_list(
        self, installation: DaisyInstallation, device: DaisyDevice
    ) -> list[DaisyStatus]:
        status_device_list = self._post(
            "teleco/services/status-device-list",
            {
                "idInstallation": installation.idInstallation,
                "idInstallationDevice": device.idInstallationDevice,
            },
        )

        return [DaisyStatus(**x) for x in status_device_list["statusitemList"]]

    def _scenario_list(self, installation: DaisyInstallation):
        req = self._post(
            "teleco/services/scenario-list",
            {
                "idInstallation": installation.idInstallation,
            },
        )

        return req

    def _command_scenario_list(self, installation: DaisyInstallation, szenario_id):
        req = self._post(
            "teleco/services/command-scenario-list",
            json={
                "idInstallation": installation.idInstallation,
                "idInstallationScenario": szenario_id,
            },
        )
        return req

    def feed_the_commands(
        self,
        installation: DaisyInstallation,
        commandsList: list[dict],
        ignore_ack=False,
    ):
        res = self._tmate20_post(
            "teleco/services/tmate20/feedthecommands/",
            json={
                "commandsList": commandsList,
                "idInstallation": installation.instCode,
                "idScenario": 0,
                "isScenario": False,
            },
        )
        if res["MessageID"] != "WS-000":
            raise Exception(res)

        if ignore_ack:
            return {"success": None}

        return self._get_ack(installation, res["ActionReference"])

    def _get_ack(self, installation: DaisyInstallation, action_reference: str):
        res = self._tmate20_post(
            "teleco/services/tmate20/getackcommand/",
            json={
                "id": action_reference,
                "idInstallation": installation.instCode,
                "idSession": self.idSession,
            },
        )
        if res["MessageID"] != "WS-300":
            raise AssertionError()
        if res["MessageText"] == "RCV":
            sleep(0.5)
            return self._get_ack(installation, action_reference)
        if res["MessageText"] == "PROC":
            return {"success": True}
        return {"success": False}
