#!/usr/bin/env python
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import String

class Listener(Node):
    def __init__(self):
        super().__init__('listener')
        self.subscription = self.create_subscription(
            String,
            'chatter',
            self.listener_callback,
            10)
        self.subscription  # prevent unused variable warning

    def listener_callback(self, msg):
        self.get_logger().info('I heard: "%s"' % msg.data)

def main(args=None):
    rclpy.init(args=args)
    listener = Listener()
    try:
        rclpy.spin(listener)
    except (KeyboardInterrupt, ExternalShutdownException):
        # On Ctrl-C rclpy's own signal handler tears the context down, so spin()
        # raises ExternalShutdownException rather than KeyboardInterrupt.
        pass
    finally:
        listener.destroy_node()
        # That same handler may already have shut the context down; calling
        # shutdown twice raises "rcl_shutdown already called".
        if rclpy.ok():
            rclpy.shutdown()
        
if __name__ == '__main__':
    main()