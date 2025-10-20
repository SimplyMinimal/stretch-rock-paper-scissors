#!/usr/bin/env python3

from dataclasses import dataclass
from enum import Enum
import os
import signal
import subprocess
import click
import time
import random
import stretch_body.robot
import rclpy
from rclpy.node import Node
from sound_play.libsoundplay import SoundClient
import threading

@dataclass
class JointValues:
    gripper: float
    wrist_yaw: float
    wrist_roll: float

    def to_dict(self):
        return {
            'gripper': self.gripper,
            'wrist_yaw': self.wrist_yaw,
            'wrist_roll': self.wrist_roll
        }

class Guestures(Enum):
    RESET = 'reset'
    ROCK = 'rock'
    PAPER = 'paper'
    SCISSORS = 'scissors'

    def get_joint_values(self):
        gestures:dict[Guestures, JointValues] = {
            Guestures.RESET: JointValues(100.0,0.0,0.0),
            Guestures.ROCK: JointValues(0.0,0.0,0.0),
            Guestures.PAPER: JointValues(0.0,1.57,0.0),
             Guestures.SCISSORS: JointValues(100.0,0.0,1.57)
        }

        return gestures[self]
    
class RockPaperScissors:
    robot:stretch_body.robot.Robot 
    def __init__(self):
        self.valid_moves = ['rock', 'paper', 'scissors']
        
        # Initialize ROS2 and sound_play
        rclpy.init()
        self.node = Node('rps_game')
        self.soundhandle = SoundClient(node=self.node)
        time.sleep(1)  # Wait for publisher to register
        
    def init_robot(self):
        self.robot = stretch_body.robot.Robot()
        if not self.robot.startup():
            raise click.ClickException("Failed to initialize the robot")
        
        # Get the wrist joints
        self.wrist_yaw = self.robot.end_of_arm.get_joint('wrist_yaw')
        self.wrist_roll = self.robot.end_of_arm.get_joint('wrist_roll')

    def cleanup(self):
        if self.robot:
            self.robot.stop()
        rclpy.shutdown()

    def speak(self, text):
        """Use sound_play for text-to-speech"""
        self.soundhandle.say(text)
        # Give time for speech to complete
        time.sleep(len(text) * 0.1)

    def move_arm_animation(self, word):
        """Move the arm up and down while speaking a word"""
        current_height = self.robot.lift.status['pos']
        up_distance = 0.1  # 10cm up
        
        # Move up
        self.robot.lift.move_by(up_distance)
        self.robot.push_command()
        
        # Speak the word while moving
        thread = threading.Thread(target=self.speak, args=(word,))
        thread.start()
        
        time.sleep(0.5)
        
        # Move back down
        self.robot.lift.move_to(current_height)
        self.robot.push_command()
        time.sleep(0.5)
        
        # Wait for speech to complete
        thread.join()

    def make_gesture(self, gesture:Guestures):
        joint_values = gesture.get_joint_values()
        # Set wrist orientations
        self.wrist_yaw.move_to(joint_values.wrist_yaw)
        self.wrist_roll.move_to(joint_values.wrist_roll)
        self.robot.push_command()
        time.sleep(1)  # Wait for wrist to rotate
        
        # Set gripper position
        self.robot.end_of_arm.move_to('stretch_gripper', joint_values.gripper)
        self.robot.push_command()
        time.sleep(1)

    def determine_winner(self, stretch_choice, player_choice):
        if stretch_choice == player_choice:
            return "It's a tie!"
        elif (
            (stretch_choice == 'rock' and player_choice == 'scissors') or
            (stretch_choice == 'paper' and player_choice == 'rock') or
            (stretch_choice == 'scissors' and player_choice == 'paper')
        ):
            return "Stretch wins!"
        else:
            return "You win!"

    def play_round(self):
        stretch_choice = random.choice(self.valid_moves)
        
        # Announce the start
        self.speak("Let's play!")
        click.echo("\nGet ready...")
        time.sleep(1)

        # Move arm up and down while announcing each word
        for word in ["Rock", "Paper", "Scissors"]:
            click.echo(f"{word}...", nl=False)
            self.move_arm_animation(word)
        
        self.speak("Shoot!")
        click.echo("Shoot!\n")

        # Make the robot's gesture
        self.make_gesture(Guestures[stretch_choice.upper()])
        click.echo(click.style(f"stretch played: {stretch_choice}", fg='blue'))
        self.speak(f"I choose {stretch_choice}")

        return stretch_choice

@click.group()
def cli():
    """Rock Paper Scissors game with the Stretch Robot! 🤖✌️"""
    pass

@click.command()
def home_robot():
    """Home the robot and prepare for the game"""
    subprocess.Popen(["stretch_free_robot_process.py"]).wait()
    subprocess.Popen(["stretch_robot_home.py"]).wait()

cli.add_command(home_robot)

@click.command()
@click.option('--rounds', '-r', default=1, help='Number of rounds to play')
def play(rounds):
    """Play Rock Paper Scissors against the robot"""
    sound_play_process = subprocess.Popen(["ros2", "run", "sound_play", "soundplay_node.py"], text=False) 
    
    time.sleep(2)

    game = RockPaperScissors()

    try:
        game.init_robot()
        game.speak("Hello! I'm ready to play Rock Paper Scissors!")
        
        for round_num in range(1, rounds + 1):

            game.robot.lift.move_to(0.5)
            game.robot.push_command()
            game.robot.wait_command()
            game.make_gesture(Guestures.RESET)

            if rounds > 1:
                click.echo(click.style(f"\nRound {round_num}", fg='green', bold=True))
                game.speak(f"Round {round_num}")
            
            stretch_choice = game.play_round()

            # Get player's move
            player_choice = click.prompt(
                'What did you play',
                type=click.Choice(['rock', 'paper', 'scissors'], case_sensitive=False)
            )

            # Determine and announce winner
            result = game.determine_winner(stretch_choice, player_choice)
            click.echo(click.style(f"\n{result}", fg='bright_green', bold=True))
            game.speak(result)

        if rounds > 1:
            game.speak("Thanks for playing!")

    except click.ClickException as e:
        click.echo(click.style(f"Error: {str(e)}", fg='red', bold=True))
    except KeyboardInterrupt:
        click.echo("\nGame interrupted by user")
        game.speak("Game interrupted. Goodbye!")
    finally:
        game.cleanup()
        os.killpg(os.getpgid(pid=sound_play_process.pid), signal.SIGTERM)

cli.add_command(play)

@cli.command()
def moves():
    """Show the available moves"""
    click.echo(click.style("\nAvailable moves:", fg='green'))
    click.echo("🤜  rock     - Vertical closed gripper")
    click.echo("✋  paper    - Horizontal closed gripper")
    click.echo("✌️  scissors - Vertical open gripper (rotated 90°)")

if __name__ == '__main__':
    cli()
