import React, { useEffect } from 'react';
import { StatusBar } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { RecognitionEngineProvider } from './src/hooks/useRecognitionEngine';
import { AuthProvider, useAuth } from './src/app/auth/AuthContext';
import { AppNavigator } from './src/navigation/AppNavigator';
import { colors } from './src/theme/theme';
import { startAutoSync } from './src/app/services/AttendanceSyncService';
import { useRecognitionEngine } from './src/hooks/useRecognitionEngine';

function AutoSyncBootstrap() {
  const { settings } = useRecognitionEngine();
  const { userId } = useAuth();
  useEffect(() => {
    startAutoSync(
      () => settings.backendBaseUrl,
      () => settings.autoSyncOnReconnect,
      () => userId,
    );
  }, [settings.backendBaseUrl, settings.autoSyncOnReconnect, userId]);
  return null;
}

function App(): React.JSX.Element {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <StatusBar barStyle="light-content" backgroundColor={colors.background} />
        <RecognitionEngineProvider>
          <AuthProvider>
            <AutoSyncBootstrap />
            <AppNavigator />
          </AuthProvider>
        </RecognitionEngineProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

export default App;