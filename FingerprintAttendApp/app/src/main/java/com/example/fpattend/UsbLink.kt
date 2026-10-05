package com.example.fpattend

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import com.hoho.android.usbserial.driver.UsbSerialDriver
import com.hoho.android.usbserial.driver.UsbSerialPort
import com.hoho.android.usbserial.driver.UsbSerialProber

class UsbLink(private val ctx: Context) {
    companion object { const val ACTION_PERMISSION = "com.example.fpattend.USB_PERMISSION" }

    private val usb = ctx.getSystemService(Context.USB_SERVICE) as UsbManager

    fun findDriver(): UsbSerialDriver? =
        UsbSerialProber.getDefaultProber().findAllDrivers(usb).firstOrNull()

    fun hasPermission(d: UsbDevice) = usb.hasPermission(d)

    fun requestPermission(d: UsbDevice) {
        val flags = if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
        val pi = PendingIntent.getBroadcast(
            ctx, 0, Intent(ACTION_PERMISSION).setPackage(ctx.packageName), flags)
        usb.requestPermission(d, pi)
    }

    /** 57600 8N1, as on the ZW101 datasheet. */
    fun open(driver: UsbSerialDriver): UsbSerialPort {
        val conn = usb.openDevice(driver.device) ?: throw IllegalStateException("could not open USB device")
        val port = driver.ports[0]
        port.open(conn)
        port.setParameters(57600, 8, UsbSerialPort.STOPBITS_1, UsbSerialPort.PARITY_NONE)
        return port
    }
}
