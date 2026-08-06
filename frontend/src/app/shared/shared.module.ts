import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';

import { SignInComponent } from './sign-in/sign-in.component';

/**
 * Declares the reusable Sign In screen so both the Edge and Central feature
 * modules can route to it (parameterized by `data.dashboard`).
 */
@NgModule({
  declarations: [SignInComponent],
  imports: [CommonModule, FormsModule, RouterModule],
  exports: [SignInComponent],
})
export class SharedModule {}
