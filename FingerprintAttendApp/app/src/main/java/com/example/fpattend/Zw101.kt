package com.example.fpattend

import com.hoho.android.usbserial.driver.UsbSerialPort
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

const val OK = 0x00
const val NO_FINGER = 0x02
const val NOT_FOUND = 0x09
const val NO_REPLY = -1

fun codeName(c: Int): String = when (c) {
    NO_REPLY -> "no reply from sensor"
    0x00 -> "OK"
    0x01 -> "packet receive error"
    0x02 -> "no finger"
    0x03 -> "image capture failed"
    0x06 -> "image too messy"
    0x07 -> "too few feature points"
    0x09 -> "not found"
    0x0A -> "the two scans did not match"
    0x0B -> "ID beyond library capacity"
    0x10 -> "delete failed"
    0x13 -> "wrong password"
    0x15 -> "no valid image"
    0x18 -> "flash write error"
    else -> "code 0x%02X".format(c)
}

class Ack(val code: Int, val data: ByteArray)
class Found(val code: Int, val id: Int, val score: Int)

private fun u16(b: ByteArray, i: Int) = ((b[i].toInt() and 0xFF) shl 8) or (b[i + 1].toInt() and 0xFF)

/** Packet format (from Adafruit files): EF 01 | FF FF FF FF | type | len(2) | data | checksum(2) */
class Zw101(private val port: UsbSerialPort) {
    private val lock = Mutex()
    var capacity = 50          // datasheet: 50 templates; replaced by the value read from the module
        private set

    /** Run several commands without another coroutine interleaving. */
    suspend fun <T> session(block: suspend Zw101.() -> T): T = lock.withLock { block() }

    private fun build(vararg d: Int): ByteArray {
        val len = d.size + 2
        val p = ByteArray(11 + d.size)
        p[0] = 0xEF.toByte(); p[1] = 0x01
        for (i in 2..5) p[i] = 0xFF.toByte()
        p[6] = 0x01                       // command packet
        p[7] = (len shr 8).toByte(); p[8] = len.toByte()
        d.forEachIndexed { i, v -> p[9 + i] = v.toByte() }
        var sum = 0
        for (i in 6 until 9 + d.size) sum += p[i].toInt() and 0xFF
        p[9 + d.size] = (sum shr 8).toByte(); p[10 + d.size] = sum.toByte()
        return p
    }

    private fun drain() {
        val b = ByteArray(64)
        while (port.read(b, 5) > 0) { /* discard stale bytes */ }
    }

    private fun readAck(timeoutMs: Long): Ack? {
        val acc = ByteArray(128); var n = 0
        val tmp = ByteArray(64)
        val end = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < end) {
            val r = port.read(tmp, 50)
            for (i in 0 until r) if (n < acc.size) acc[n++] = tmp[i]
            var s = -1
            for (i in 0 until n - 1) if (acc[i] == 0xEF.toByte() && acc[i + 1] == 0x01.toByte()) { s = i; break }
            if (s >= 0 && n - s >= 9) {
                val len = u16(acc, s + 7)
                if (len < 3 || len > 100) return null
                if (n - s >= 9 + len) {
                    var sum = 0
                    for (i in s + 6 until s + 9 + len - 2) sum += acc[i].toInt() and 0xFF
                    if ((sum and 0xFFFF) != u16(acc, s + 9 + len - 2)) return null   // bad checksum
                    if (acc[s + 6].toInt() != 0x07) return null                        // not an ACK packet
                    return Ack(acc[s + 9].toInt() and 0xFF, acc.copyOfRange(s + 10, s + 9 + len - 2))
                }
            }
        }
        return null
    }

    private suspend fun cmd(vararg d: Int, timeoutMs: Long = 1500): Ack? = withContext(Dispatchers.IO) {
        try { drain(); port.write(build(*d), 1000); readAck(timeoutMs) } catch (e: Exception) { null }
    }

    // ---- single commands ----
    suspend fun verify(): Boolean = cmd(0x13, 0, 0, 0, 0)?.code == OK     // default password 00 00 00 00

    suspend fun readParams(): Boolean {
        val a = cmd(0x0F) ?: return false
        if (a.code != OK || a.data.size < 6) return false
        val cap = u16(a.data, 4)
        if (cap in 1..1000) capacity = cap
        return true
    }

    suspend fun templateCount(): Int {
        val a = cmd(0x1D) ?: return -1
        return if (a.code == OK && a.data.size >= 2) u16(a.data, 0) else -1
    }

    suspend fun getImage(): Int = cmd(0x01)?.code ?: NO_REPLY
    suspend fun img2Tz(slot: Int): Int = cmd(0x02, slot)?.code ?: NO_REPLY

    suspend fun search(slot: Int): Found {
        val a = cmd(0x04, slot, 0, 0, capacity shr 8, capacity and 0xFF, timeoutMs = 2500)
            ?: return Found(NO_REPLY, 0, 0)
        if (a.code != OK || a.data.size < 4) return Found(a.code, 0, 0)
        return Found(OK, u16(a.data, 0), u16(a.data, 2))
    }

    suspend fun regModel(): Int = cmd(0x05)?.code ?: NO_REPLY
    suspend fun store(id: Int): Int = cmd(0x06, 1, id shr 8, id and 0xFF)?.code ?: NO_REPLY
    suspend fun delete(id: Int): Int = cmd(0x0C, id shr 8, id and 0xFF, 0, 1)?.code ?: NO_REPLY

    // ---- helpers ----
    suspend fun waitForFinger(present: Boolean, timeoutMs: Long): Boolean {
        val end = System.currentTimeMillis() + timeoutMs
        var absentCount = 0
        while (System.currentTimeMillis() < end) {
            val c = getImage()
            if (present && c == OK) return true
            if (!present && c == NO_FINGER) { if (++absentCount >= 2) return true } else absentCount = 0
            delay(80)
        }
        return false
    }

    /** Returns null on success, otherwise an error text. */
    suspend fun enroll(id: Int, say: (String) -> Unit): String? {
        if (id !in 0 until capacity) return "ID must be 0 to ${capacity - 1} (module capacity $capacity)"
        say("Place finger on the sensor...")
        if (!waitForFinger(true, 15000)) return "timed out waiting for finger"
        var c = img2Tz(1)
        if (c != OK) return "first scan unusable (${codeName(c)}). Try again."
        val dup = search(1)
        if (dup.code == OK) return "this finger is already enrolled as ID ${dup.id}"
        say("Remove finger...")
        if (!waitForFinger(false, 10000)) return "finger was not removed"
        say("Place the SAME finger again...")
        if (!waitForFinger(true, 15000)) return "timed out (second scan)"
        c = img2Tz(2)
        if (c != OK) return "second scan unusable (${codeName(c)}). Try again."
        c = regModel()
        if (c != OK) return "scans did not match (${codeName(c)}). Start again."
        c = store(id)
        if (c != OK) return "store failed (${codeName(c)})"
        return null
    }
}
