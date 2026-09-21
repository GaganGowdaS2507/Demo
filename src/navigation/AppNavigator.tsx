import React from 'react';
import { NavigationContainer, DefaultTheme } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { colors } from '../theme/theme';
import { useAuth } from '../app/auth/AuthContext';
import { useRecognitionEngine } from '../hooks/useRecognitionEngine';
import { LoginScreen } from '../screens/auth/LoginScreen';
import { SetupScreen } from '../screens/SetupScreen';
import { FacultyHomeScreen } from '../screens/faculty/FacultyHomeScreen';
import { MyClassesScreen } from '../screens/faculty/MyClassesScreen';
import { AttendanceScreen } from '../screens/faculty/AttendanceScreen';
import { PendingAttendanceScreen } from '../screens/faculty/PendingAttendanceScreen';
import { FacultyProfileScreen } from '../screens/faculty/FacultyProfileScreen';
import { GroupPhotoScreen } from '../screens/faculty/GroupPhotoScreen';

const FacultyTab = createBottomTabNavigator();
const FacultyStack = createNativeStackNavigator();

const FacultyHomeStack = () => (
  <FacultyStack.Navigator screenOptions={{ headerShown: false }}>
    <FacultyStack.Screen name="Dashboard" component={FacultyHomeScreen} />
    <FacultyStack.Screen name="MyClasses" component={MyClassesScreen} />
    <FacultyStack.Screen name="Attendance" component={AttendanceScreen} />
    <FacultyStack.Screen name="GroupPhoto" component={GroupPhotoScreen} />
    <FacultyStack.Screen name="Profile" component={FacultyProfileScreen} />
  </FacultyStack.Navigator>
);

const navTheme = {
  ...DefaultTheme,
  colors: {
    ...DefaultTheme.colors,
    background: colors.background, card: colors.surface,
    text: colors.textPrimary, border: colors.border, primary: colors.accent,
  },
};

const FacultyTabs = () => (
  <FacultyTab.Navigator
    screenOptions={{
      headerShown: false,
      tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.border },
      tabBarActiveTintColor: colors.accent,
      tabBarInactiveTintColor: colors.textSecondary,
    }}
  >
    <FacultyTab.Screen name="Home" component={FacultyHomeStack} />
    <FacultyTab.Screen name="Pending" component={PendingAttendanceScreen} />
  </FacultyTab.Navigator>
);

export const AppNavigator: React.FC = () => {
  const { isLoading, isLoggedIn, needsSetup, completeSetup, logout } = useAuth();
  const { settings } = useRecognitionEngine();
  if (isLoading) return null;

  return (
    <NavigationContainer theme={navTheme}>
      {!isLoggedIn ? (
        <LoginScreen />
      ) : needsSetup ? (
        <SetupScreen
          baseUrl={settings.backendBaseUrl}
          onComplete={completeSetup}
          onCancelLogin={logout}
        />
      ) : (
        <FacultyTabs />
      )}
    </NavigationContainer>
  );
};