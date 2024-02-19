from dataclasses import dataclass
from time import sleep
from typing import Literal

import requests

base_url = "https://tmate.telecoautomation.com/"


@dataclass
class DaisyStatus:
    idInstallationDeviceStatusitem: int
    idDevicetypeStatusitemModel: int
    statusitemCode: str
    statusItem: str
    statusValue: str
    lowlevelStatusitem: None


@dataclass
class DaisyInstallation:
    activetimer: str
    firmwareVersion: str
    idInstallation: int
    idInstallationDevice: int
    instCode: str
    instDescription: str
    installationOrder: int
    latitude: float
    longitude: float
    weekend: str  # list[str]
    workdays: str  # list[str]

    client: "TelecoDaisy"

    def status(self):
        return self.client.get_installation_is_active(self)


@dataclass
class DaisyDevice:
    activetimer: str
    deviceCode: str
    deviceIndex: int
    deviceOrder: int
    directOnly: None
    favorite: str
    feedback: str
    idDevicemodel: int
    idDevicetype: int
    idInstallationDevice: int
    label: str
    remoteControlCode: str

    client: "TelecoDaisy"
    installation: DaisyInstallation

    def update_state(self) -> list[DaisyStatus]:
        return self.client.status_device_list(self.installation, self)


class DaisyCover(DaisyDevice):
    position: int | None = None
    is_closed: bool | None = None

    def update_state(self):
        stati = super().update_state()
        for status in stati:
            if status.statusitemCode == "OPEN_CLOSE":
                if status.statusValue == "CLOSE":
                    self.is_closed = True
                elif status.statusValue == "OPEN":
                    self.is_closed = False
                else:
                    self.is_closed = None
            if status.statusitemCode == "LEVEL":
                self.position = int(status.statusValue)

    def open_cover(self, percent: Literal["33", "66", "100"] = None):
        if percent == "100":
            return self._open_stop_close("open")
        self._control_cover(percent)

    def stop_cover(self):
        self._open_stop_close("stop")

    def close_cover(self):
        self._open_stop_close("close")

    def _open_stop_close(self, open_stop_close: Literal["open", "stop", "close"]):
        osc_map = {
            "open": ["OPEN", 94, "CH4"],
            "stop": ["STOP", 95, "CH7"],
            "close": ["CLOSE", 96, "CH1"],
        }
        c_param, c_id, c_ll = osc_map[open_stop_close]
        return self.client.feed_the_commands(
            installation=self.installation,
            commandsList=[
                {
                    "deviceCode": str(self.deviceIndex),
                    "idInstallationDevice": self.idInstallationDevice,
                    "commandAction": "OPEN_STOP_CLOSE",
                    "commandId": c_id,
                    "commandParam": c_param,
                    "lowlevelCommand": c_ll,
                }
            ],
        )

    def _control_cover(self, percent: Literal["33", "66", "100"]):
        percent_map = {
            "33": ["LEV2", 97, "CH2"],
            "66": ["LEV3", 98, "CH3"],
            "100": ["LEV4", 99, "CH4"],
        }
        c_param, c_id, c_ll = percent_map[percent]

        return self.client.feed_the_commands(
            installation=self.installation,
            commandsList=[
                {
                    "deviceCode": str(self.deviceIndex),
                    "idInstallationDevice": self.idInstallationDevice,
                    "commandAction": "LEVEL",
                    "commandId": c_id,
                    "commandParam": c_param,
                    "lowlevelCommand": c_ll,
                }
            ],
        )


class DaisyLight(DaisyDevice):
    is_on: bool | None = None
    brightness: int | None = None  # from 0 to 100
    rgb: tuple[int, int, int] | None = None

    def update_state(self):
        stati = super().update_state()
        for status in stati:
            if status.statusitemCode == "POWER":
                self.is_on = status.statusValue == "ON"
            if status.statusitemCode == "COLOR":
                val = status.statusValue
                self.brightness = int(val[1:4])
                self.rgb = (int(val[5:8]), int(val[9:12]), int(val[13:16]))

    def set_rgb_and_brightness(
        self, rgb: tuple[int, int, int] = None, brightness: int = None
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
        return self.client.feed_the_commands(
            installation=self.installation,
            commandsList=[
                {
                    "commandAction": "COLOR",
                    "commandId": 137,
                    "commandParam": v,
                    "deviceCode": str(self.deviceIndex),
                    "idInstallationDevice": self.idInstallationDevice,
                }
            ],
        )

    def turn_off(self):
        return self.client.feed_the_commands(
            installation=self.installation,
            commandsList=[
                {
                    "commandAction": "POWER",
                    "commandId": 138,
                    "commandParam": "OFF",
                    "deviceCode": str(self.deviceIndex),
                    "idInstallationDevice": self.idInstallationDevice,
                }
            ],
        )


@dataclass
class DaisyRoom:
    idInstallationRoom: int
    idRoomtype: int
    roomDescription: str
    roomOrder: int
    deviceList: list[DaisyDevice]


class TelecoDaisy:
    idAccount: int | None = None
    idSession: str | None = None

    def __init__(self, email, password):
        self.s = requests.Session()
        self.s.auth = ("teleco", "tmate20")
        self.email = email
        self.password = password

    def login(self):
        login = self.s.post(
            base_url + "teleco/services/account-login",
            json={"email": self.email, "pwd": self.password},
        )
        login_json = login.json()
        if login_json["codEsito"] != "S":
            raise Exception(login_json)

        self.idAccount = login_json["valRisultato"]["idAccount"]
        self.idSession = login_json["valRisultato"]["idSession"]

    def get_account_installation_list(self) -> list[DaisyInstallation]:
        req = self.s.post(
            base_url + "teleco/services/account-installation-list",
            json={"idSession": self.idSession, "idAccount": self.idAccount},
        )
        req_json = req.json()
        if req_json["codEsito"] != "S":
            raise Exception(req_json)

        installations = []
        for inst in req_json["valRisultato"]["installationList"]:
            installations += [DaisyInstallation(**inst, client=self)]
        return installations

    def get_installation_is_active(self, installation: DaisyInstallation):
        req = self.s.post(
            base_url + "teleco/services/tmate20/nodestatus",
            json={
                "idSession": self.idSession,
                "idInstallation": installation.idInstallation,
            },
        )
        req_json = req.json()
        return req_json["nodeActive"]

    def get_room_list(self, installation: DaisyInstallation) -> list[DaisyRoom]:
        req = self.s.post(
            base_url + "teleco/services/room-list",
            json={
                "idSession": self.idSession,
                "idAccount": self.idAccount,
                "idInstallation": installation.idInstallation,
            },
        )
        req_json = req.json()
        if req_json["codEsito"] != "S":
            raise Exception(req_json)

        rooms = []
        for room in req_json["valRisultato"]["roomList"]:
            devices = []
            for device in room.pop("deviceList"):
                if device["idDevicetype"] == 23:
                    devices += [
                        DaisyLight(**device, client=self, installation=installation)
                    ]
                elif device["idDevicetype"] == 24:
                    devices += [
                        DaisyCover(**device, client=self, installation=installation)
                    ]
            rooms += [DaisyRoom(**room, deviceList=devices)]
        return rooms

    def status_device_list(
        self, installation: DaisyInstallation, device: DaisyDevice
    ) -> list[DaisyStatus]:
        req = self.s.post(
            base_url + "teleco/services/status-device-list",
            json={
                "idSession": self.idSession,
                "idAccount": self.idAccount,
                "idInstallation": installation.idInstallation,
                "idInstallationDevice": device.idInstallationDevice,
            },
        )
        req_json = req.json()
        if req_json["codEsito"] != "S":
            raise Exception(req_json)

        return [DaisyStatus(**x) for x in req_json["valRisultato"]["statusitemList"]]

    def feed_the_commands(
        self,
        installation: DaisyInstallation,
        commandsList: list[dict],
        ignore_ack=False,
    ):
        req = self.s.post(
            base_url + "teleco/services/tmate20/feedthecommands/",
            json={
                "commandsList": commandsList,
                "idInstallation": installation.instCode,
                "idSession": self.idSession,
                "idScenario": 0,
                "isScenario": False,
            },
        )
        req_json = req.json()

        if req_json["MessageID"] != "WS-000":
            raise Exception(req_json)

        if ignore_ack:
            return {"success": None}

        return self._get_ack(installation, req_json["ActionReference"])

    def _get_ack(self, installation: DaisyInstallation, action_reference: str):
        req = self.s.post(
            base_url + "teleco/services/tmate20/getackcommand/",
            json={
                "id": action_reference,
                "idInstallation": installation.instCode,
                "idSession": self.idSession,
            },
        )
        req_json = req.json()
        assert req_json["MessageID"] == "WS-300"
        if req_json["MessageText"] == "RCV":
            sleep(0.5)
            return self._get_ack(installation, action_reference)
        if req_json["MessageText"] == "PROC":
            return {"success": True}
        return {"success": False}
