#!/usr/bin/env python
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import String

class Talker(Node):
    def __init__(self):
        super().__init__('talker')
        self.publisher_ = self.create_publisher(String, 'chatter', 10)
        timer_period = 0.5  # seconds
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.i = 0

    def timer_callback(self):
        msg = String()
        msg.data = 'Hello World: %d' % self.i
        self.publisher_.publish(msg)
        self.get_logger().info('Publishing: "%s"' % msg.data)
        self.i += 1
        
def main(args=None):
    rclpy.init(args=args)
    talker = Talker()
    try:
        rclpy.spin(talker)
    except (KeyboardInterrupt, ExternalShutdownException):
        # On Ctrl-C rclpy's own signal handler tears the context down, so spin()
        # raises ExternalShutdownException rather than KeyboardInterrupt.
        pass
    finally:
        talker.destroy_node()
        # That same handler may already have shut the context down; calling
        # shutdown twice raises "rcl_shutdown already called".
        if rclpy.ok():
            rclpy.shutdown()
        
if __name__ == '__main__':
    main()