import React, { forwardRef, useImperativeHandle, useRef, useEffect } from 'react';
import { View, StyleSheet, Text } from 'react-native';
import { Camera, useCameraDevice, useCameraPermission } from 'react-native-vision-camera';

export interface PhoneCameraViewHandle {
  /** Grabs the currently-displayed frame from the device camera and returns a file:// URI. */
  captureFrameUri(): Promise<string>;
}

interface Props {
  position?: 'front' | 'back';
  isActive?: boolean;
}

export const PhoneCameraView = forwardRef<PhoneCameraViewHandle, Props>(
  ({ position = 'front', isActive = true }, ref) => {
    const cameraRef = useRef<Camera>(null);
    const device = useCameraDevice(position);
    const { hasPermission, requestPermission } = useCameraPermission();

    useEffect(() => {
      if (!hasPermission) {
        requestPermission();
      }
    }, [hasPermission, requestPermission]);

    useImperativeHandle(ref, () => ({
      async captureFrameUri() {
        if (!cameraRef.current) {
          throw new Error('Camera ref not mounted');
        }
        const photo = await cameraRef.current.takePhoto({
          flash: 'off',
          enableShutterSound: false,
        });
        return `file://${photo.path}`;
      },
    }));

    if (!hasPermission) {
      return (
        <View style={styles.container}>
          <Text style={styles.text}>Camera permission required</Text>
        </View>
      );
    }

    if (!device) {
      return (
        <View style={styles.container}>
          <Text style={styles.text}>No {position} camera device found</Text>
        </View>
      );
    }

    return (
      <View style={styles.container}>
        <Camera
          ref={cameraRef}
          style={StyleSheet.absoluteFill}
          device={device}
          isActive={isActive}
          photo={true}
          onError={(error) => {
            console.log('[PhoneCameraView] camera runtime error:', error?.message ?? String(error));
          }}
        />
      </View>
    );
  },
);

const styles = StyleSheet.create({
  container: {
    height: 260,
    borderRadius: 10,
    overflow: 'hidden',
    backgroundColor: '#000',
    justifyContent: 'center',
    alignItems: 'center',
  },
  text: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '500',
  },
});
