package com.example.fpattend

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Bitmap
import android.hardware.usb.UsbManager
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import android.widget.Toast
import androidx.core.content.FileProvider
import androidx.core.content.ContextCompat
import java.io.ByteArrayOutputStream
import java.io.File

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()
    private lateinit var link: UsbLink

    private val usbReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                UsbLink.ACTION_PERMISSION -> {
                    val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                    if (granted) {
                        openUsbPort()
                    } else {
                        vm.sensorStatus = "USB permission denied by user"
                        vm.addLog("USB permission denied")
                    }
                }
                UsbManager.ACTION_USB_DEVICE_DETACHED -> {
                    vm.disconnect("USB fingerprint device unplugged")
                }
                UsbManager.ACTION_USB_DEVICE_ATTACHED -> {
                    connectUsb()
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        link = UsbLink(this)

        val filter = IntentFilter().apply {
            addAction(UsbLink.ACTION_PERMISSION)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
        }
        ContextCompat.registerReceiver(this, usbReceiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)

        setContent {
            MaterialTheme(
                colorScheme = lightColorScheme(
                    primary = Color(0xFF1E88E5),
                    secondary = Color(0xFF00897B),
                    tertiary = Color(0xFF5E35B1),
                    background = Color(0xFFF8F9FA),
                    surface = Color.White
                )
            ) {
                AppRoot(vm = vm, onConnectUsb = { connectUsb() })
            }
        }

        connectUsb()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        connectUsb()
    }

    override fun onDestroy() {
        super.onDestroy()
        try { unregisterReceiver(usbReceiver) } catch (_: Exception) {}
    }

    private fun connectUsb() {
        if (vm.connected) return
        val driver = link.findDriver()
        if (driver == null) {
            vm.sensorStatus = "No USB-serial adapter found. Plug device into Type-C port."
            return
        }
        if (link.hasPermission(driver.device)) {
            openUsbPort()
        } else {
            vm.sensorStatus = "Requesting USB permission..."
            link.requestPermission(driver.device)
        }
    }

    private fun openUsbPort() {
        val driver = link.findDriver() ?: return
        try {
            val port = link.open(driver)
            vm.attach(port)
        } catch (e: Exception) {
            vm.sensorStatus = "Could not open USB port: ${e.message}"
            vm.addLog("USB open error: ${e.message}")
        }
    }
}

// ── Root Screen ───────────────────────────────────────────────────────────────
@Composable
fun AppRoot(vm: MainViewModel, onConnectUsb: () -> Unit) {
    if (!vm.isLoggedIn) {
        LoginScreen(vm)
    } else {
        MainDashboard(vm, onConnectUsb)
    }
}

// ── Login Screen ──────────────────────────────────────────────────────────────
@Composable
fun LoginScreen(vm: MainViewModel) {
    var email by remember { mutableStateOf(vm.currentUserEmail.ifBlank { "renitablossom@gmail.com" }) }
    var password by remember { mutableStateOf("faculty123") }
    var isLoggingIn by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFFF4F6F8))
            .padding(24.dp),
        contentAlignment = Alignment.Center
    ) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(16.dp),
            elevation = CardDefaults.cardElevation(defaultElevation = 6.dp)
        ) {
            Column(
                modifier = Modifier.padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Icon(
                    imageVector = Icons.Default.Fingerprint,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(64.dp)
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "AttendAI Fingerprint",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    "Faculty Portal (Online & Offline)",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Color.Gray
                )
                Spacer(Modifier.height(20.dp))

                OutlinedTextField(
                    value = vm.serverUrl,
                    onValueChange = { vm.serverUrl = it },
                    label = { Text("Server URL") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(10.dp))

                OutlinedTextField(
                    value = email,
                    onValueChange = { email = it },
                    label = { Text("Faculty Email") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(10.dp))

                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    label = { Text("Password") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(10.dp))

                OutlinedTextField(
                    value = vm.deviceId,
                    onValueChange = { vm.deviceId = it },
                    label = { Text("Device ID") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(16.dp))

                if (vm.loginError.isNotEmpty()) {
                    Text(
                        vm.loginError,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(bottom = 8.dp)
                    )
                }

                Button(
                    onClick = {
                        isLoggingIn = true
                        vm.login(email, password) {
                            isLoggingIn = false
                        }
                    },
                    enabled = !isLoggingIn,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(50.dp),
                    shape = RoundedCornerShape(10.dp)
                ) {
                    if (isLoggingIn) {
                        CircularProgressIndicator(color = Color.White, modifier = Modifier.size(24.dp))
                    } else {
                        Text("Login", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                    }
                }

                Spacer(Modifier.height(12.dp))
                Text(
                    "Works offline after your first login!",
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.Gray
                )
            }
        }
    }
}

// ── Main Dashboard Screen ─────────────────────────────────────────────────────
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainDashboard(vm: MainViewModel, onConnectUsb: () -> Unit) {
    var selectedNavTab by remember { mutableIntStateOf(0) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("AttendAI Portal", fontWeight = FontWeight.Bold, fontSize = 18.sp)
                        Text(
                            "${vm.currentUserName} • ${if (vm.isOfflineMode) "Offline" else "Online"}",
                            fontSize = 12.sp,
                            color = Color.DarkGray
                        )
                    }
                },
                actions = {
                    if (!vm.connected) {
                        IconButton(onClick = onConnectUsb) {
                            Icon(Icons.Default.Usb, contentDescription = "Connect USB", tint = Color.Red)
                        }
                    }
                    if (vm.pendingQueueCount > 0) {
                        IconButton(onClick = { vm.flushQueue() }) {
                            BadgedBox(badge = { Badge { Text("${vm.pendingQueueCount}") } }) {
                                Icon(Icons.Default.Sync, contentDescription = "Sync Queue", tint = Color(0xFF1E88E5))
                            }
                        }
                    }
                    IconButton(onClick = { vm.logout() }) {
                        Icon(Icons.Default.Logout, contentDescription = "Logout")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.White)
            )
        },
        bottomBar = {
            NavigationBar(containerColor = Color.White) {
                NavigationBarItem(
                    selected = selectedNavTab == 0,
                    onClick = { selectedNavTab = 0 },
                    icon = { Icon(Icons.Default.School, contentDescription = null) },
                    label = { Text("My Classes") }
                )
                NavigationBarItem(
                    selected = selectedNavTab == 1,
                    onClick = { selectedNavTab = 1 },
                    icon = { Icon(Icons.Default.Checklist, contentDescription = null) },
                    label = { Text("Attendance") }
                )
                NavigationBarItem(
                    selected = selectedNavTab == 2,
                    onClick = { selectedNavTab = 2 },
                    icon = { Icon(Icons.Default.Fingerprint, contentDescription = null) },
                    label = { Text("Sensor") }
                )
                NavigationBarItem(
                    selected = selectedNavTab == 3,
                    onClick = { selectedNavTab = 3 },
                    icon = { Icon(Icons.Default.Settings, contentDescription = null) },
                    label = { Text("Settings") }
                )
            }
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .background(Color(0xFFF8F9FA))
        ) {
            SensorStatusBar(vm = vm, onConnectUsb = onConnectUsb)

            when (selectedNavTab) {
                0 -> MyClassesTab(vm, onOpenAttendance = { selectedNavTab = 1 })
                1 -> AttendanceStudioTab(vm)
                2 -> FingerprintManagementTab(vm)
                3 -> SettingsAndSyncTab(vm)
            }
        }
    }
}

// ── Sensor Status Bar ─────────────────────────────────────────────────────────
@Composable
fun SensorStatusBar(vm: MainViewModel, onConnectUsb: () -> Unit) {
    Surface(
        color = if (vm.connected) Color(0xFFE8F5E9) else Color(0xFFFFEBEE),
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier
                .padding(horizontal = 16.dp, vertical = 6.dp)
                .fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(9.dp)
                    .clip(CircleShape)
                    .background(if (vm.connected) Color(0xFF2E7D32) else Color(0xFFC62828))
            )
            Spacer(Modifier.width(8.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    if (vm.connected) "Fingerprint Sensor Connected (${vm.mode})" else "Sensor Disconnected",
                    fontWeight = FontWeight.Bold,
                    fontSize = 12.sp,
                    color = if (vm.connected) Color(0xFF1B5E20) else Color(0xFFB71C1C)
                )
                Text(
                    vm.sensorStatus,
                    fontSize = 11.sp,
                    color = Color.DarkGray,
                    maxLines = 1
                )
            }
            if (!vm.connected) {
                Button(
                    onClick = onConnectUsb,
                    contentPadding = PaddingValues(horizontal = 10.dp, vertical = 2.dp),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Text("Connect", fontSize = 11.sp)
                }
            }
        }
    }
}

// ── Tab 0: My Classes (Filtered by Today, Upcoming, Past) ───────────────────────
@Composable
fun MyClassesTab(vm: MainViewModel, onOpenAttendance: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        Text("My Classes & Timetable", fontWeight = FontWeight.Bold, fontSize = 20.sp)
        Spacer(Modifier.height(10.dp))

        // Period Filter Pills (Today, Upcoming, Past)
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            val filters = listOf(
                Triple("today", "Today", vm.todaySessions.size),
                Triple("upcoming", "Upcoming", vm.upcomingSessions.size),
                Triple("past", "Past", vm.pastSessions.size)
            )

            for ((key, label, count) in filters) {
                val isSelected = vm.sessionPeriod == key
                FilterChip(
                    selected = isSelected,
                    onClick = { vm.sessionPeriod = key },
                    label = { Text("$label ($count)", fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal) },
                    modifier = Modifier.weight(1f),
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = MaterialTheme.colorScheme.primary,
                        selectedLabelColor = Color.White
                    )
                )
            }
        }

        Spacer(Modifier.height(12.dp))

        val sessions = vm.currentFilteredSessions
        if (sessions.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Default.EventBusy, contentDescription = null, tint = Color.Gray, modifier = Modifier.size(48.dp))
                    Spacer(Modifier.height(8.dp))
                    Text("No ${vm.sessionPeriod} classes found.", color = Color.Gray, fontSize = 14.sp)
                    Spacer(Modifier.height(12.dp))
                    Button(onClick = { vm.syncAllData() }) {
                        Icon(Icons.Default.Sync, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Sync Timetable")
                    }
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                items(sessions) { s ->
                    val isActive = vm.activeSession?.sessionId == s.sessionId
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable {
                                vm.openSession(s)
                                onOpenAttendance()
                            },
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = if (isActive) Color(0xFFE3F2FD) else Color.White
                        ),
                        border = if (isActive) BorderStroke(2.dp, Color(0xFF1E88E5)) else null,
                        elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
                    ) {
                        Column(modifier = Modifier.padding(14.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(s.subjectName, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                                Surface(
                                    color = if (s.status == "completed") Color(0xFFE8F5E9) else Color(0xFFFFF3E0),
                                    shape = RoundedCornerShape(6.dp)
                                ) {
                                    Text(
                                        s.status.uppercase(),
                                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                                        fontSize = 10.sp,
                                        fontWeight = FontWeight.Bold,
                                        color = if (s.status == "completed") Color(0xFF2E7D32) else Color(0xFFE65100)
                                    )
                                }
                            }
                            Spacer(Modifier.height(4.dp))
                            Text(
                                "Section: ${s.sectionLabel} • Time: ${s.startTime} - ${s.endTime}",
                                fontSize = 13.sp,
                                color = Color.DarkGray
                            )
                            Text(
                                "Date: ${s.sessionDate}",
                                fontSize = 12.sp,
                                color = Color.Gray
                            )
                            Spacer(Modifier.height(10.dp))

                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.End
                            ) {
                                Button(
                                    onClick = {
                                        vm.openSession(s)
                                        onOpenAttendance()
                                    },
                                    shape = RoundedCornerShape(8.dp),
                                    contentPadding = PaddingValues(horizontal = 14.dp, vertical = 6.dp)
                                ) {
                                    Icon(Icons.Default.FactCheck, contentDescription = null, modifier = Modifier.size(16.dp))
                                    Spacer(Modifier.width(6.dp))
                                    Text("Take Attendance")
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

// ── Tab 1: Attendance Studio (Fingerprint + Roster Manual + Group Photo) ───────
@Composable
fun AttendanceStudioTab(vm: MainViewModel) {
    val session = vm.activeSession

    if (session == null) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(24.dp),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(Icons.Default.School, contentDescription = null, tint = Color.Gray, modifier = Modifier.size(54.dp))
                Spacer(Modifier.height(12.dp))
                Text("No Class Selected", fontWeight = FontWeight.Bold, fontSize = 18.sp)
                Text("Select a class from the 'My Classes' tab to take attendance.", color = Color.Gray, fontSize = 13.sp)
            }
        }
        return
    }

    var subTab by remember { mutableIntStateOf(0) } // 0 = Fingerprint, 1 = Roster & Manual, 2 = Group Photo

    Column(modifier = Modifier.fillMaxSize()) {
        // Active Class Summary Header Banner
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
            shape = RoundedCornerShape(12.dp),
            colors = CardDefaults.cardColors(containerColor = Color.White),
            elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
        ) {
            Column(modifier = Modifier.padding(12.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(session.subjectName, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                        Text("${session.sectionLabel} • ${session.startTime} - ${session.endTime}", fontSize = 12.sp, color = Color.DarkGray)
                    }
                    // Stats Pill
                    val total = maxOf(1, vm.sessionRoster.size)
                    val percent = (vm.presentCount * 100) / total
                    Surface(
                        color = Color(0xFFE8F5E9),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Text(
                            "${vm.presentCount}/${vm.sessionRoster.size} ($percent%)",
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                            fontWeight = FontWeight.Bold,
                            color = Color(0xFF2E7D32),
                            fontSize = 12.sp
                        )
                    }
                }
            }
        }

        // Sub-tabs (Fingerprint, Student Roster & Manual, Group Photo)
        TabRow(
            selectedTabIndex = subTab,
            containerColor = Color.White,
            contentColor = MaterialTheme.colorScheme.primary
        ) {
            Tab(
                selected = subTab == 0,
                onClick = { subTab = 0 },
                text = { Text("Fingerprint", fontSize = 12.sp, fontWeight = FontWeight.SemiBold) },
                icon = { Icon(Icons.Default.Fingerprint, contentDescription = null, modifier = Modifier.size(18.dp)) }
            )
            Tab(
                selected = subTab == 1,
                onClick = { subTab = 1 },
                text = { Text("Roster & Manual", fontSize = 12.sp, fontWeight = FontWeight.SemiBold) },
                icon = { Icon(Icons.Default.ListAlt, contentDescription = null, modifier = Modifier.size(18.dp)) }
            )
            Tab(
                selected = subTab == 2,
                onClick = { subTab = 2 },
                text = { Text("Group Photo", fontSize = 12.sp, fontWeight = FontWeight.SemiBold) },
                icon = { Icon(Icons.Default.CameraAlt, contentDescription = null, modifier = Modifier.size(18.dp)) }
            )
        }

        when (subTab) {
            0 -> FingerprintAttendanceView(vm)
            1 -> RosterAndManualView(vm)
            2 -> GroupPhotoRecognitionView(vm)
        }
    }
}

// ── Sub-tab 0: Fingerprint Attendance View ────────────────────────────────────
@Composable
fun FingerprintAttendanceView(vm: MainViewModel) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(16.dp),
            colors = CardDefaults.cardColors(containerColor = Color.White),
            elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Box(
                    modifier = Modifier
                        .size(80.dp)
                        .clip(CircleShape)
                        .background(if (vm.mode == "Identify") Color(0xFFE3F2FD) else Color(0xFFEEEEEE)),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        Icons.Default.Fingerprint,
                        contentDescription = null,
                        modifier = Modifier.size(50.dp),
                        tint = if (vm.mode == "Identify") Color(0xFF1E88E5) else Color.Gray
                    )
                }
                Spacer(Modifier.height(12.dp))
                Text(
                    if (vm.mode == "Identify") "Fingerprint Scanner is ACTIVE" else "Scanner is PAUSED",
                    fontWeight = FontWeight.Bold,
                    fontSize = 16.sp,
                    color = if (vm.mode == "Identify") Color(0xFF1E88E5) else Color.Gray
                )
                Text(
                    if (vm.mode == "Identify") "Place finger on the Type-C sensor to mark attendance" else "Press start to resume attendance scanning",
                    fontSize = 12.sp,
                    color = Color.Gray
                )
                Spacer(Modifier.height(14.dp))

                Row {
                    Button(
                        onClick = { vm.startIdentify() },
                        enabled = vm.connected && vm.mode != "Identify",
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Icon(Icons.Default.PlayArrow, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("Start Scanner")
                    }
                    Spacer(Modifier.width(10.dp))
                    OutlinedButton(
                        onClick = { vm.stopIdentify() },
                        enabled = vm.mode == "Identify",
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Icon(Icons.Default.Stop, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("Pause")
                    }
                }
            }
        }

        Spacer(Modifier.height(14.dp))

        // Last Matched Hero Card
        if (vm.lastMatchedStudentName.isNotEmpty()) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
                colors = CardDefaults.cardColors(
                    containerColor = if (vm.isMatchSuccess) Color(0xFFE8F5E9) else Color(0xFFFFEBEE)
                )
            ) {
                Row(
                    modifier = Modifier.padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(
                        if (vm.isMatchSuccess) Icons.Default.CheckCircle else Icons.Default.Cancel,
                        contentDescription = null,
                        tint = if (vm.isMatchSuccess) Color(0xFF2E7D32) else Color(0xFFC62828),
                        modifier = Modifier.size(36.dp)
                    )
                    Spacer(Modifier.width(12.dp))
                    Column {
                        Text(
                            vm.lastMatchedStudentName,
                            fontWeight = FontWeight.Bold,
                            fontSize = 16.sp,
                            color = if (vm.isMatchSuccess) Color(0xFF1B5E20) else Color(0xFFB71C1C)
                        )
                        Text(
                            "USN: ${vm.lastMatchedUsn} • Fingerprint Score: ${vm.lastMatchScore}",
                            fontSize = 13.sp,
                            color = Color.DarkGray
                        )
                    }
                }
            }
            Spacer(Modifier.height(14.dp))
        }

        // Live Marked Present List for this session
        Text(
            "Present via Fingerprint (${vm.presentCount})",
            fontWeight = FontWeight.Bold,
            fontSize = 15.sp,
            modifier = Modifier.align(Alignment.Start)
        )
        Spacer(Modifier.height(8.dp))

        val presentList = vm.sessionRoster.filter { it.status == "present" }
        if (presentList.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentAlignment = Alignment.Center
            ) {
                Text("No students scanned yet. Place finger on sensor.", color = Color.Gray, fontSize = 13.sp)
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(presentList) { st ->
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(10.dp),
                        colors = CardDefaults.cardColors(containerColor = Color.White)
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column {
                                Text(st.name, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                                Text("USN: ${st.usn} • [${st.method}]", fontSize = 12.sp, color = Color.Gray)
                            }
                            Surface(
                                color = Color(0xFFE8F5E9),
                                shape = RoundedCornerShape(6.dp)
                            ) {
                                Text(
                                    "PRESENT",
                                    color = Color(0xFF2E7D32),
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 11.sp,
                                    modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

// ── Sub-tab 1: Roster & Manual Marking View ───────────────────────────────────
@Composable
fun RosterAndManualView(vm: MainViewModel) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
    ) {
        // Bulk Action Buttons
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Button(
                onClick = { vm.bulkMarkAll("present") },
                shape = RoundedCornerShape(8.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF2E7D32)),
                modifier = Modifier.weight(1f)
            ) {
                Icon(Icons.Default.DoneAll, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("Mark All Present", fontSize = 12.sp)
            }

            OutlinedButton(
                onClick = { vm.bulkMarkAll("absent") },
                shape = RoundedCornerShape(8.dp),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = Color(0xFFC62828)),
                modifier = Modifier.weight(1f)
            ) {
                Icon(Icons.Default.RemoveDone, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("Mark All Absent", fontSize = 12.sp)
            }
        }

        Spacer(Modifier.height(10.dp))

        // Search Bar
        OutlinedTextField(
            value = vm.rosterSearchQuery,
            onValueChange = { vm.rosterSearchQuery = it },
            placeholder = { Text("Search by name or USN...") },
            leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, tint = Color.Gray) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(10.dp)
        )

        Spacer(Modifier.height(12.dp))

        // Stats summary chips
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                "Students (${vm.filteredRoster.size})",
                fontWeight = FontWeight.Bold,
                fontSize = 15.sp
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Surface(color = Color(0xFFE8F5E9), shape = RoundedCornerShape(6.dp)) {
                    Text("Present: ${vm.presentCount}", color = Color(0xFF2E7D32), fontSize = 12.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp))
                }
                Surface(color = Color(0xFFFFEBEE), shape = RoundedCornerShape(6.dp)) {
                    Text("Absent: ${vm.absentCount}", color = Color(0xFFC62828), fontSize = 12.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp))
                }
                IconButton(
                    onClick = { vm.activeSession?.let { vm.loadRosterForSession(it) } },
                    modifier = Modifier.size(28.dp)
                ) {
                    Icon(Icons.Default.Refresh, contentDescription = "Refresh Roster", tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
                }
            }
        }

        Spacer(Modifier.height(8.dp))

        if (vm.filteredRoster.isEmpty()) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                contentAlignment = Alignment.Center
            ) {
                Text("No students in this section roster.", color = Color.Gray)
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                items(vm.filteredRoster) { student ->
                    val isPresent = student.status == "present"
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { vm.toggleStudentAttendance(student) },
                        shape = RoundedCornerShape(10.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = if (isPresent) Color(0xFFF1F8E9) else Color.White
                        ),
                        border = if (isPresent) BorderStroke(1.dp, Color(0xFF81C784)) else null,
                        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(student.name, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                                Text("USN: ${student.usn}", fontSize = 12.sp, color = Color.DarkGray)
                                if (student.method.isNotEmpty()) {
                                    Text("via ${student.method}", fontSize = 11.sp, color = Color.Gray)
                                }
                            }

                            // Interactive Toggle Switch / Pill
                            Button(
                                onClick = { vm.toggleStudentAttendance(student) },
                                shape = RoundedCornerShape(8.dp),
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = if (isPresent) Color(0xFF2E7D32) else Color(0xFFECEFF1)
                                ),
                                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                            ) {
                                Text(
                                    if (isPresent) "PRESENT" else "ABSENT",
                                    color = if (isPresent) Color.White else Color(0xFF37474F),
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 11.sp
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

// ── Sub-tab 2: Group Photo AI Recognition View ────────────────────────────────
@Composable
fun GroupPhotoRecognitionView(vm: MainViewModel) {
    val context = LocalContext.current
    var tempPhotoFile by remember { mutableStateOf<File?>(null) }

    val galleryLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetMultipleContents()
    ) { uris ->
        for (uri in uris) {
            try {
                context.contentResolver.openInputStream(uri)?.use { stream ->
                    val bytes = stream.readBytes()
                    vm.addGroupPhoto(bytes)
                }
            } catch (e: Exception) {
                Toast.makeText(context, "Error loading image: ${e.localizedMessage}", Toast.LENGTH_SHORT).show()
            }
        }
    }

    val takePictureLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.TakePicture()
    ) { success ->
        val file = tempPhotoFile
        if (success && file != null && file.exists()) {
            try {
                val bytes = file.readBytes()
                if (bytes.isNotEmpty()) {
                    vm.addGroupPhoto(bytes)
                }
            } catch (e: Exception) {
                Toast.makeText(context, "Error reading captured photo: ${e.localizedMessage}", Toast.LENGTH_SHORT).show()
            } finally {
                try { file.delete() } catch (_: Exception) {}
            }
        }
    }

    val launchCameraIntent = {
        try {
            val file = File.createTempFile("group_photo_", ".jpg", context.cacheDir)
            val uri = FileProvider.getUriForFile(
                context,
                "${context.packageName}.fileprovider",
                file
            )
            tempPhotoFile = file
            takePictureLauncher.launch(uri)
        } catch (e: Exception) {
            Toast.makeText(context, "Could not open camera: ${e.localizedMessage}", Toast.LENGTH_LONG).show()
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            launchCameraIntent()
        } else {
            Toast.makeText(context, "Camera permission is required to capture photos", Toast.LENGTH_LONG).show()
        }
    }

    val onCameraClick = {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            launchCameraIntent()
        } else {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                colors = CardDefaults.cardColors(containerColor = Color.White),
                elevation = CardDefaults.cardElevation(defaultElevation = 2.dp)
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.CameraAlt, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(8.dp))
                        Text("Classroom Group Photo Recognition", fontWeight = FontWeight.Bold, fontSize = 16.sp)
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Upload 1 to 3 wide-angle classroom photos. The server's AI will detect and recognize all student faces at once.",
                        fontSize = 12.sp,
                        color = Color.Gray
                    )
                    Spacer(Modifier.height(14.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        Button(
                            onClick = onCameraClick,
                            enabled = vm.groupPhotos.size < 3 && !vm.isProcessingGroupPhoto,
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.weight(1f)
                        ) {
                            Icon(Icons.Default.PhotoCamera, contentDescription = null, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("Camera", fontSize = 12.sp)
                        }

                        OutlinedButton(
                            onClick = { galleryLauncher.launch("image/*") },
                            enabled = vm.groupPhotos.size < 3 && !vm.isProcessingGroupPhoto,
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.weight(1f)
                        ) {
                            Icon(Icons.Default.PhotoLibrary, contentDescription = null, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("Gallery", fontSize = 12.sp)
                        }
                    }

                    Spacer(Modifier.height(10.dp))
                    Text("Selected Photos: ${vm.groupPhotos.size} / 3", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Color.DarkGray)

                    if (vm.groupPhotos.isNotEmpty()) {
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            vm.groupPhotos.forEachIndexed { idx, _ ->
                                Surface(
                                    color = Color(0xFFE3F2FD),
                                    shape = RoundedCornerShape(8.dp)
                                ) {
                                    Row(
                                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Text("Photo #${idx + 1}", fontSize = 12.sp, color = Color(0xFF1976D2))
                                        Spacer(Modifier.width(4.dp))
                                        Icon(
                                            Icons.Default.Close,
                                            contentDescription = "Remove",
                                            modifier = Modifier
                                                .size(14.dp)
                                                .clickable { vm.removeGroupPhoto(idx) },
                                            tint = Color.Red
                                        )
                                    }
                                }
                            }
                        }

                        Spacer(Modifier.height(14.dp))
                        Button(
                            onClick = { vm.processGroupPhotos() },
                            enabled = !vm.isProcessingGroupPhoto,
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            if (vm.isProcessingGroupPhoto) {
                                CircularProgressIndicator(color = Color.White, modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(8.dp))
                            }
                            Text("Process Photos with AI")
                        }
                    }

                    if (vm.groupPhotoStatusMessage.isNotEmpty()) {
                        Spacer(Modifier.height(10.dp))
                        Surface(
                            color = Color(0xFFE8F5E9),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(
                                vm.groupPhotoStatusMessage,
                                modifier = Modifier.padding(10.dp),
                                fontSize = 12.sp,
                                color = Color(0xFF1B5E20),
                                fontWeight = FontWeight.Medium
                            )
                        }
                    }
                }
            }
        }

        // Recognition Results List
        if (vm.hasRunGroupPhotoRecognition) {
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        "Recognized Students (${vm.groupPhotoMatches.size})",
                        fontWeight = FontWeight.Bold,
                        fontSize = 15.sp
                    )
                    Button(
                        onClick = { vm.confirmGroupPhotoAttendance() },
                        enabled = vm.groupPhotoMatches.any { it.selected },
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Text("Confirm Attendance")
                    }
                }
            }

            if (vm.groupPhotoMatches.isEmpty()) {
                item {
                    Card(modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(10.dp)) {
                        Box(modifier = Modifier.padding(16.dp), contentAlignment = Alignment.Center) {
                            Text("No matching student faces found in the uploaded photos.", color = Color.Gray)
                        }
                    }
                }
            } else {
                items(vm.groupPhotoMatches) { match ->
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(10.dp),
                        colors = CardDefaults.cardColors(containerColor = Color.White)
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.weight(1f)) {
                                Checkbox(
                                    checked = match.selected,
                                    onCheckedChange = { match.selected = it }
                                )
                                Spacer(Modifier.width(8.dp))
                                Column {
                                    Text(match.name, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                                    Text("USN: ${match.usn} • Score: ${(match.score * 100).toInt()}%", fontSize = 12.sp, color = Color.Gray)
                                }
                            }
                            Surface(
                                color = Color(0xFFE8F5E9),
                                shape = RoundedCornerShape(6.dp)
                            ) {
                                Text(
                                    "${(match.score * 100).toInt()}%",
                                    color = Color(0xFF2E7D32),
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 11.sp,
                                    modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

// ── Tab 2: Fingerprint Management (Enroll / Delete) ───────────────────────────
@Composable
fun FingerprintManagementTab(vm: MainViewModel) {
    var templateIdText by remember { mutableStateOf("") }
    var rollText by remember { mutableStateOf("") }
    var enrollStatusMsg by remember { mutableStateOf("") }
    var deleteIdText by remember { mutableStateOf("") }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // Enrolment Card
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                colors = CardDefaults.cardColors(containerColor = Color.White)
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.PersonAdd, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(8.dp))
                        Text("Enroll Student Fingerprint", fontWeight = FontWeight.Bold, fontSize = 16.sp)
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Guides through two scans on the Type-C sensor, checks duplicate finger, and links student USN.",
                        fontSize = 12.sp,
                        color = Color.Gray
                    )
                    Spacer(Modifier.height(14.dp))

                    OutlinedTextField(
                        value = templateIdText,
                        onValueChange = { templateIdText = it },
                        label = { Text("Template ID (0 to ${vm.sensorCapacity - 1})") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(Modifier.height(10.dp))

                    OutlinedTextField(
                        value = rollText,
                        onValueChange = { rollText = it },
                        label = { Text("Student USN / Roll (e.g. 1MS21CS001)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(Modifier.height(14.dp))

                    if (enrollStatusMsg.isNotEmpty()) {
                        Surface(
                            color = Color(0xFFE3F2FD),
                            shape = RoundedCornerShape(8.dp),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(
                                enrollStatusMsg,
                                modifier = Modifier.padding(10.dp),
                                fontSize = 13.sp,
                                color = Color(0xFF0D47A1),
                                fontWeight = FontWeight.Medium
                            )
                        }
                        Spacer(Modifier.height(12.dp))
                    }

                    Button(
                        onClick = {
                            enrollStatusMsg = "Starting enrollment..."
                            vm.enrollFingerprint(templateIdText, rollText) { msg ->
                                enrollStatusMsg = msg
                            }
                        },
                        enabled = vm.connected && vm.mode != "Enroll",
                        shape = RoundedCornerShape(8.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Icon(Icons.Default.TouchApp, contentDescription = null)
                        Spacer(Modifier.width(6.dp))
                        Text("Start 2-Scan Enrollment")
                    }
                }
            }
        }

        // Delete Card
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                colors = CardDefaults.cardColors(containerColor = Color.White)
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.DeleteOutline, contentDescription = null, tint = Color(0xFFC62828))
                        Spacer(Modifier.width(8.dp))
                        Text("Delete Fingerprint Template", fontWeight = FontWeight.Bold, fontSize = 16.sp)
                    }
                    Spacer(Modifier.height(10.dp))

                    OutlinedTextField(
                        value = deleteIdText,
                        onValueChange = { deleteIdText = it },
                        label = { Text("Template ID to delete") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(Modifier.height(12.dp))

                    Button(
                        onClick = {
                            vm.deleteFingerprint(deleteIdText) { res ->
                                enrollStatusMsg = res
                            }
                        },
                        enabled = vm.connected,
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFC62828)),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Text("Delete from Sensor & Server")
                    }
                }
            }
        }

        // Enrolled Templates List
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    "Enrolled Templates (${vm.templatesList.size})",
                    fontWeight = FontWeight.Bold,
                    fontSize = 15.sp
                )
                TextButton(onClick = { vm.refreshSensorCount() }) {
                    Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Refresh Count")
                }
            }
        }

        if (vm.templatesList.isEmpty()) {
            item {
                Card(modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(10.dp)) {
                    Box(modifier = Modifier.padding(20.dp), contentAlignment = Alignment.Center) {
                        Text("No templates enrolled yet.", color = Color.Gray, fontSize = 13.sp)
                    }
                }
            }
        } else {
            items(vm.templatesList) { t ->
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(10.dp),
                    colors = CardDefaults.cardColors(containerColor = Color.White)
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(
                                modifier = Modifier
                                    .size(36.dp)
                                    .clip(CircleShape)
                                    .background(Color(0xFFE3F2FD)),
                                contentAlignment = Alignment.Center
                            ) {
                                Text("#${t.templateId}", fontWeight = FontWeight.Bold, color = Color(0xFF1976D2), fontSize = 12.sp)
                            }
                            Spacer(Modifier.width(12.dp))
                            Column {
                                Text(t.name, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                                Text("USN: ${t.usn}", fontSize = 12.sp, color = Color.Gray)
                            }
                        }
                        IconButton(onClick = { vm.deleteFingerprint(t.templateId.toString()) {} }) {
                            Icon(Icons.Default.Delete, contentDescription = "Delete", tint = Color.Gray)
                        }
                    }
                }
            }
        }
    }
}

// ── Tab 3: Settings & Offline Queue ───────────────────────────────────────────
@Composable
fun SettingsAndSyncTab(vm: MainViewModel) {
    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // Offline Queue Card
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                colors = CardDefaults.cardColors(containerColor = Color.White)
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Storage, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(8.dp))
                        Text("Offline Queue Management", fontWeight = FontWeight.Bold, fontSize = 16.sp)
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Attendance marked while offline is saved securely in the device database until synced.",
                        fontSize = 12.sp,
                        color = Color.Gray
                    )
                    Spacer(Modifier.height(10.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            "Pending Uploads: ${vm.pendingQueueCount}",
                            fontWeight = FontWeight.Bold,
                            fontSize = 15.sp,
                            color = if (vm.pendingQueueCount > 0) Color(0xFFE65100) else Color(0xFF2E7D32)
                        )
                        Button(
                            onClick = { vm.flushQueue() },
                            enabled = vm.pendingQueueCount > 0 && !vm.isFlushingQueue,
                            shape = RoundedCornerShape(8.dp)
                        ) {
                            if (vm.isFlushingQueue) {
                                CircularProgressIndicator(color = Color.White, modifier = Modifier.size(16.dp))
                                Spacer(Modifier.width(6.dp))
                            }
                            Text("Flush Queue")
                        }
                    }
                }
            }
        }

        // Offline Data Setup Sync Card
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                colors = CardDefaults.cardColors(containerColor = Color.White)
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.CloudDownload, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(8.dp))
                        Text("Offline Data Setup", fontWeight = FontWeight.Bold, fontSize = 16.sp)
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Download timetable, student rosters, and fingerprint templates to enable 100% offline classroom attendance.",
                        fontSize = 12.sp,
                        color = Color.Gray
                    )
                    Spacer(Modifier.height(12.dp))

                    Button(
                        onClick = { vm.syncAllData() },
                        enabled = !vm.isSyncingData,
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        if (vm.isSyncingData) {
                            CircularProgressIndicator(color = Color.White, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                        }
                        Text("Sync All Data From Server")
                    }

                    if (vm.syncMessage.isNotEmpty()) {
                        Spacer(Modifier.height(8.dp))
                        Text(vm.syncMessage, fontSize = 12.sp, color = Color(0xFF00796B))
                    }
                }
            }
        }

        // Server Configuration Card
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                colors = CardDefaults.cardColors(containerColor = Color.White)
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Default.Settings, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                        Spacer(Modifier.width(8.dp))
                        Text("Connection Configuration", fontWeight = FontWeight.Bold, fontSize = 16.sp)
                    }
                    Spacer(Modifier.height(14.dp))

                    OutlinedTextField(
                        value = vm.serverUrl,
                        onValueChange = { vm.serverUrl = it },
                        label = { Text("Server URL") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(Modifier.height(10.dp))

                    OutlinedTextField(
                        value = vm.deviceId,
                        onValueChange = { vm.deviceId = it },
                        label = { Text("Device ID") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(Modifier.height(14.dp))

                    Button(
                        onClick = { vm.saveSettings() },
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(8.dp)
                    ) {
                        Text("Save Configuration")
                    }
                }
            }
        }

        // Diagnostic Sensor Logs
        item {
            Text("Diagnostic Logs", fontWeight = FontWeight.Bold, fontSize = 15.sp)
            Spacer(Modifier.height(4.dp))
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(200.dp),
                shape = RoundedCornerShape(10.dp),
                colors = CardDefaults.cardColors(containerColor = Color(0xFF263238))
            ) {
                LazyColumn(modifier = Modifier.padding(10.dp)) {
                    items(vm.logs) { log ->
                        Text(log, color = Color(0xFFCFD8DC), fontSize = 11.sp, fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace)
                    }
                }
            }
        }
    }
}
