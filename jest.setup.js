/**
 * Jest setup for the merged RNSharedApp + Face Recognition Playground app.
 *
 * The core recognition logic (EmbeddingUtils, SimilarityCalculator, etc.) is
 * pure JS/TS and needs no mocking. The mocks below exist so that screens and
 * `App.tsx` (which pull in native modules transitively) can still be
 * required/rendered in a Jest (Node) environment without crashing on
 * `NativeModules.X is not available` errors, since none of these native
 * modules have a real native implementation to link against under Jest.
 */

// react-native-gesture-handler ships an official Jest mock.
import 'react-native-gesture-handler/jestSetup';

// react-native-safe-area-context ships an official Jest mock.
jest.mock('react-native-safe-area-context', () =>
  require('react-native-safe-area-context/jest/mock').default,
);

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

jest.mock('react-native-sqlite-storage', () => ({
  enablePromise: jest.fn(),
  openDatabase: jest.fn().mockResolvedValue({
    executeSql: jest.fn().mockResolvedValue([{rows: {length: 0, item: () => undefined}}]),
  }),
}));

jest.mock('@react-native-ml-kit/face-detection', () => ({
  __esModule: true,
  default: {detect: jest.fn().mockResolvedValue([])},
}));

jest.mock('onnxruntime-react-native', () => ({
  InferenceSession: {create: jest.fn()},
  Tensor: jest.fn(),
}));

jest.mock('@shopify/react-native-skia', () => ({
  Skia: {
    Data: {fromBase64: jest.fn()},
    Image: {MakeImageFromEncoded: jest.fn()},
  },
}));

jest.mock('react-native-fs', () => ({
  readFile: jest.fn(),
  exists: jest.fn().mockResolvedValue(true),
  unlink: jest.fn().mockResolvedValue(undefined),
}));

jest.mock('@react-native-community/image-editor', () => ({
  cropImage: jest.fn(),
}));

jest.mock('@bam.tech/react-native-image-resizer', () => ({
  createResizedImage: jest.fn(),
}));

jest.mock('react-native-webview', () => {
  const React = require('react');
  const { View } = require('react-native');
  return {
    WebView: React.forwardRef((props, ref) => React.createElement(View, props)),
  };
});

jest.mock('react-native-image-picker', () => ({
  launchCamera: jest.fn(),
  launchImageLibrary: jest.fn(),
}));

jest.mock('@react-native-community/slider', () => 'Slider');

jest.mock('@react-native-community/netinfo', () => ({
  addEventListener: jest.fn(() => jest.fn()),
  fetch: jest.fn().mockResolvedValue({ isConnected: true, isInternetReachable: true }),
}));

jest.mock('react-native-sha256', () => ({
  sha256: jest.fn().mockImplementation((str) => Promise.resolve(`hashed_${str}`)),
}));

jest.mock('react-native-vision-camera', () => ({
  Camera: 'Camera',
  useCameraDevice: jest.fn().mockReturnValue({ id: 'back' }),
  useCameraPermission: jest.fn().mockReturnValue({ hasPermission: true, requestPermission: jest.fn() }),
}));
